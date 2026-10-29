"""bol.com assortment content monitor.

From the 2026-10-28 meeting transcript, Rob received a bol.com platform
report over ~300 listings flagging per-attribute content problems:

  * images at 1000x1000 where the platform wants 1500x1500
  * titles / descriptions too long or too short for the segment
  * keyword relevance scored per segment (adapters, phones, cables)
  * and per segment the house style "dates from 2021" and is no longer
    appealing to the market

The agent reads the listing table and produces a prioritised fix list.  It
never edits a live listing -- publishing is a human action.
"""
from __future__ import annotations

from ..db.db import Database
from .base import audit, request_approval

MIN_IMAGE_PX = 1500
MIN_TITLE = 40
MAX_TITLE = 120
MIN_DESC = 120
MAX_DESC = 900


class AssortmentAgent:
    name = "assortment_monitor"

    def __init__(self, db: Database):
        self.db = db

    def scan(self) -> dict:
        listings = self.db.query("SELECT * FROM assortment WHERE online=1")
        issues: list[dict] = []
        for l in listings:
            problems = []
            if l["image_px"] and l["image_px"] < MIN_IMAGE_PX:
                problems.append(f"image {l['image_px']}px < {MIN_IMAGE_PX}px")
            if l["title_len"] and (l["title_len"] < MIN_TITLE or l["title_len"] > MAX_TITLE):
                problems.append(f"title length {l['title_len']} outside {MIN_TITLE}-{MAX_TITLE}")
            if l["description_len"] and (l["description_len"] < MIN_DESC
                                        or l["description_len"] > MAX_DESC):
                problems.append(
                    f"description length {l['description_len']} outside {MIN_DESC}-{MAX_DESC}")
            if float(l["keyword_score"] or 0) < 3:
                problems.append(f"keyword score {l['keyword_score']} low")
            if problems:
                issues.append({"listing_id": l["listing_id"],
                               "account": l["account"],
                               "title": l["title"],
                               "problems": problems})
        # worst first
        issues.sort(key=lambda i: len(i["problems"]), reverse=True)
        if issues:
            request_approval(self.db, self.name, "assortment_content_fix",
                             {"issues": issues[:100]}, risk="medium")
        audit(self.db, self.name, "assortment_scanned", "assortment", None,
              {"listings": len(listings), "issues": len(issues)})
        return {"listings": len(listings), "issues": len(issues),
                "worst": issues[:10]}

    def segment_scores(self) -> list[dict]:
        return self.db.query(
            """SELECT account, ROUND(AVG(keyword_score),2) AS keyword,
                      ROUND(AVG(content_score),2) AS content, COUNT(*) AS n
               FROM assortment WHERE online=1 GROUP BY account""")
