import json
import os

from bson import ObjectId

from modules.mongo_db import company_data as mongo
from modules.minio import minio_script as minio
from modules.crawler import crawler as crawler, sustainability_reports_beautifulsoup
from modules.crawler import google_api_combined_crawler as google_api_combined_crawler
from datetime import datetime
import logging
from modules.mongo_db.company_data import ROOT_DIR

#Variable to check database statues
is_db_initialized = False


def retrieve_and_store_csr_reports(collection):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    current_year = str(datetime.now().year)
    
    #TODO: Remove limit after testing
    for document in collection.find():
        company_name = document["security"]
        ticker = document.get("symbol", "")  # Ensure ticker is present if needed
        logger.info(f"Processing company: {company_name}")

        try:
            existing_reports = document.get("csr_reports", {})

            # Find the earliest year from existing reports or default to the current year
            if existing_reports:
                earliest_year = str(min(map(int, existing_reports.keys())))  # Find the lowest year
            else:
                earliest_year = str(int(current_year) -2)  # Default to current year if no reports exist

            # Generate all years from earliest found to current year (inclusive)
            years_to_process = list(range(int(earliest_year), int(current_year)+1))
            print(years_to_process)

            update_data = {"updated_at": datetime.utcnow()}
            csr_reports = existing_reports.copy()  # Copy existing CSR reports to preserve them

            for year in years_to_process:
                year_str = str(year)

                # Skip if the year already has a CSR report URL
                if year_str in csr_reports and csr_reports[year_str]:
                    logger.info(f"Skipping {company_name} for year {year}, report already exists.")
                    continue

                # Process for current year
                if year_str == current_year:
                    try:
                        result = crawler.process_company(company_name)

                        if result == (None, None):
                            logger.warning(f"No valid result found for {company_name} for year {year}")
                            result = google_api_combined_crawler._get_report_search_results(company_name, ticker, year_str)
                            

                        # If still no results, continue to next year
                        if result == (None, None):
                            continue
                        #TODO: If the year is current year, compare the pdfs with previous year
                        webpage_url, pdf_url = result
                        csr_reports[year_str] = pdf_url
                        update_data["website_url"] = webpage_url
                    except Exception as e:
                        logger.warning(f"No valid result found for {company_name} for year {year}")
                        result = google_api_combined_crawler._get_report_search_results(company_name, ticker, year_str)

                        if result is None:
                            continue

                        webpage_url, pdf_url = result
                        csr_reports[year_str] = pdf_url
                        update_data["website_url"] = webpage_url

                else:
                    try:
                        pdf_url = google_api_combined_crawler._get_report_search_results(company_name, ticker, year_str)
                    except Exception as e:
                        logger.error(f"Error retrieving and storing CSR reports: {e}")
                        #schedule it to run again tmr
                        continue

                    if pdf_url:
                        csr_reports[year_str] = pdf_url
                    else:
                        csr_reports[year_str] = ""  # Mark as empty if no report found

            # Update only if there are changes in the csr_reports
            if csr_reports != existing_reports:  # Avoid unnecessary updates if no data changed
                update_data["csr_reports"] = csr_reports  # Update csr_reports field
                collection.update_one({"_id": document["_id"]}, {"$set": update_data})
                logger.info(f"Updated CSR report URLs for {company_name}")
            else:
                logger.info(f"No updates needed for {company_name}.")

        except Exception as e:
            logger.error(f"Error processing {company_name}: {e}")


def upload_csr_reports_to_minio(db, client, mongo_client):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    collection = db.companies

    for document in collection.find():
        try:
            minio.upload_report_to_minio(document, client, mongo_client)
            logger.info(f"Uploaded report for {document.get('security')} to MinIO")
        except Exception as e:
            logger.error(f"Error uploading {document.get('security')}: {e}")


def responsibility_reports_seed():
    mongo_client = mongo.connect_to_mongo()
    if mongo_client is None:
        exit(1)

    minio_client = minio.connect_to_minio()
    if minio_client is None:
        exit(1)

    ROOT_DIR = os.getenv("ROOT_DIR")
    seed_folder = os.path.join(ROOT_DIR, "mongo-seed")
    seed_file = os.path.join(seed_folder, "seed_data.json")

    db = mongo_client["csr_reports"]
    collection = db.companies

    # Load historical reports
    sustainability_reports_beautifulsoup.populate_reports_sustainability_reports_org(collection)
    print("Loaded historical reports")

    # Ensure uniqueness before exporting
    unique_data = []
    seen_companies = set()

    for doc in collection.find({}).limit(10):
        company_name = doc.get("security", "")  # Unique identifier
        if company_name in seen_companies:
            continue  # Skip duplicates
        seen_companies.add(company_name)

        # Convert MongoDB types to JSON serializable format
        doc.pop("_id", None)
        for key, value in doc.items():
            if isinstance(value, datetime):
                doc[key] = value.isoformat()
            elif isinstance(value, ObjectId):
                doc[key] = str(value)

        unique_data.append(doc)

    # Write unique data to JSON file
    with open(seed_file, "w", encoding="utf-8") as f:
        json.dump(unique_data, f, indent=4)

    print(f"Exported {len(unique_data)} unique documents to {seed_file}")

def populate_database():
    global is_db_initialized

    mongo_client = mongo.connect_to_mongo()
    if mongo_client is None:
        exit(1)

    minio_client = minio.connect_to_minio()
    if minio_client is None:
        exit(1)
    db = mongo_client["csr_reports"]
    # TODO: Initialize responsobility reprost as seed after loading
    mongo.import_seed_to_mongo()
    collection = db.companies

    #TODO: when API keys are out, schedule to run again a day later
    try:
        retrieve_and_store_csr_reports(collection)
    except Exception as e:
        #schedule it to run again tmr
        pass


    
    upload_csr_reports_to_minio(collection, minio_client, mongo_client)
    is_db_initialized = True
    print("Database loaded successfully: " + str(is_db_initialized))
    upload_csr_reports_to_minio(db, minio_client, mongo_client)
    return is_db_initialized


def get_latest_report():

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    mongo_client = mongo.connect_to_mongo()
    if mongo_client is None:
        exit(1)
        logger.error("Failed to connect to MongoDB")
        return
    else:
        logger.info("Connected to MongoDB")

    db = mongo_client["csr_reports"]
    collection = db.companies
    #Iterate through all documents, check if current year exists

    current_year = str(datetime.now().year)


    for document in collection.find():
        company_name = document["security"]
        ticker = document.get("symbol", "")  # Ensure ticker is present if needed
        logger.info(f"Processing company: {company_name}")

        try:
            existing_reports = document.get("csr_reports", {})

            # Find the earliest year from existing reports or default to the current year
            if existing_reports:
                latest_year = max(existing_reports.keys())
                logger.info(f"Latest year for {company_name} is {latest_year}")
            else:
                latest_year = current_year
                logger.info(f"No reports found for {company_name}, using current year")

            years_to_process = [latest_year]
                
            print(years_to_process)

            update_data = {"updated_at": datetime.utcnow()}
            csr_reports = existing_reports.copy()  # Copy existing CSR reports to preserve them

            for year in years_to_process:
                year_str = str(year)

                # Skip if the year already has a CSR report URL
                if year_str in csr_reports and csr_reports[year_str]:
                    logger.info(f"Skipping {company_name} for year {year}, report already exists.")
                    continue

                # Process for current year
                if year_str == current_year:
                    try:
                        result = crawler.process_company(company_name)

                        if result == (None, None):
                            logger.warning(f"No valid result found for {company_name} for year {year}")
                            result = google_api_combined_crawler._get_report_search_results(company_name, ticker, year_str)

                        # If still no results, continue to next year
                        if result == (None, None):
                            continue
                        else:
                            logger.info(f"Crawler:Valid result found for {company_name} for year {year}")
                        #TODO: If the year is current year, compare the pdfs with previous year
                        webpage_url, pdf_url = result
                        csr_reports[year_str] = pdf_url
                        update_data["website_url"] = webpage_url
                    except Exception as e:
                        logger.warning(f"No valid result found for {company_name} for year {year}")
                        result = google_api_combined_crawler._get_report_search_results(company_name, ticker, year_str)

                        if result is None:
                            logger.info(f"GoogleAPI Crawler:No valid result found for {company_name} for year {year}")
                            continue
                        else:
                            logger.info(f"GoogleAPI Crawler:Valid result found for {company_name} for year {year}")

                        webpage_url, pdf_url = result
                        csr_reports[year_str] = pdf_url
                        update_data["website_url"] = webpage_url

                else:
                    pdf_url = google_api_combined_crawler._get_report_search_results(company_name, ticker, year_str)

                    if pdf_url:
                        csr_reports[year_str] = pdf_url
                        logger.info(f"GoogleAPI Crawler:Valid result found for {company_name} for year {year}")
                    else:
                        csr_reports[year_str] = ""  # Mark as empty if no report found
                        logger.info(f"GoogleAPI Crawler:No valid result found for {company_name} for year {year}")

            # Update only if there are changes in the csr_reports
            if csr_reports != existing_reports:  # Avoid unnecessary updates if no data changed
                update_data["csr_reports"] = csr_reports  # Update csr_reports field
                collection.update_one({"_id": document["_id"]}, {"$set": update_data})
                logger.info(f"Updated CSR report URLs for {company_name}")
            else:
                logger.info(f"No updates needed for {company_name}.")

        except Exception as e:
            logger.error(f"Error processing {company_name}: {e}")
    

    #result = crawler.process_company(company_name)
    #return None
    #Use the webdriver to get latest report, if different from previous year add, otherwise skip
    return 

if __name__ == '__main__': 
    #mongo.reset_database()
    #responsibility_reports_seed()
    #populate_database()
    pass