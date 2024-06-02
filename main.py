import json
import os
import sys
import argparse
import requests

from models.item import Item
from models.profile import Profile


collection_items_api_url = "https://bandcamp.com/api/fancollection/1/collection_items"

# Arg parsing
parser = argparse.ArgumentParser()
parser.add_argument("URL", help="Bandcamp profile URL")
parser.add_argument("-f", "--file", help="Output file")
parser.add_argument("-F", "--format", help="Output format (json, readable)")
arguments = parser.parse_args()
if not arguments.URL:
    parser.print_usage()
    sys.stderr.write(
        f"{os.path.basename(sys.argv[0])}: error: the following arguments are required: URL\n")
    sys.exit(2)

    # Get account ID from URL
account_id = 3950257


# Get collection items for fan_id
response = requests.post(
    url=collection_items_api_url,
    headers={
        "Content-Type": "application/json",
    },
    data='{"fan_id":%s,"older_than_token":"1654875877:2285568234:p::","count":10000}' % account_id
)

items = [Item(
    item["item_id"],
    item["band_id"],
    item["url_hints"]["slug"],
    item["item_title"],
    item["item_url"],
    item["item_art_url"],
    item["download_available"]
) for item in response.json()["items"]]

profile = Profile(
    id=account_id,
    url=arguments.URL,
    items=items
)

#
# Send result to stdout or file
#
output = ""
if arguments.format == "json":
    output = json.dumps(profile.json())
elif arguments.format == "readable":
    output = json.dumps(profile.json(), indent=4)
else:
    output = json.dumps(profile.json())  # default to json

if arguments.file:
    with open(arguments.file, "w") as f:
        f.write(output)
else:
    print(output)
