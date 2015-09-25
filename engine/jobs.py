import os
import requests
import json
from aggregation_api import base_directory,AggregationAPI
from csv_output import CsvOut
import yaml
import rollbar
import traceback

def aggregate(project_id, token, href, metadata, environment):
    try:
        panoptes_file = open("/app/config/aggregation.yml","rb")
        api_details = yaml.load(panoptes_file)
        rollbar_token = api_details[environment]["rollbar"]
    except IOError:
        panoptes_file = open(base_directory+"/Databases/aggregation.yml","rb")
        api_details = yaml.load(panoptes_file)
        rollbar_token = api_details[environment]["rollbar"]

    rollbar.init(rollbar_token,environment)

    try:
        with AggregationAPI(project_id, environment=environment) as project:
            project.__migrate__()
            project.__aggregate__()

            with CsvOut(project) as writer:
                tarpath = writer.__write_out__(compress=True)
                response = send_uploading(metadata, token, href)
                url = response.json()["media"][0]["src"]
                with open(tarpath, 'rb') as tarball:
                    requests.put(url, headers={'Content-Type': 'application/x-gzip'}, data=tarball)
                os.remove(tarpath)
                send_finished(metadata, token, href)
                extra = {"project_id":project_id}

        rollbar.report_message("finished run","info",extra_data=extra)

    except Exception, err:
        print "reporting to rollbar from jobs.py"
        print traceback.format_exc()
        rollbar.report_exc_info()



def get_etag(href, token):
    response = requests.get(href, headers=headers(token), params={'admin': True})
    return response.headers['ETag']

def send_uploading(metadata, token, href):
    metadata['state'] = 'uploading'
    body = { 'media': { 'metadata': metadata } }
    return send_request(body, token, href)

def send_finished(metadata, token, href):
    metadata['state'] = 'finished'
    body = { 'media': { 'metadata': metadata } }
    return send_request(body, token, href)

def headers(token, etag=False):
    headers = { 'Accept': 'application/vnd.api+json; version=1',
                'Content-Type': 'application/json',
                'Authorization': 'Bearer '+str(token) }
    if etag:
        headers['If-Match'] = get_etag(etag, token)
    return headers

def send_request(body, token, href):
    body['admin'] = True
    return requests.put(href, headers=headers(token, etag=href), data=json.dumps(body))





