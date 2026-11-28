"""The branches that have IncoPOS. Each one has its own IncoCloud account (its own key).

Each account numbers its shop, receipts, products and product groups from 1, so a number only
means something together with its branch: every file is in the branch's own folder, and every
row in the database has the branch's id.

key (on the left) = the branch's folder, data/incopos/<key>/, and the end of its key names in
.env: INCOPOS_APP_ID_<KEY> and INCOPOS_APP_SECRET_<KEY>.
name (on the right) = the branch's name in the branches table.
A branch whose key isn't in .env yet is skipped.
"""
from pathlib import Path

DATA_DIR = Path("data/incopos")

BRANCHES = {
    "sanapiro": "სანაპირო",
    "lisi": "ლისი",
    "dolabauri": "დოლაბაური",     # the new one (29 Bochorma St), POS name ახალი კაფე
    "ivertubani": "ივერთუბანი",
}
