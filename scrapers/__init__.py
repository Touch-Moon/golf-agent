"""
Scraper registry — maps system name (from config.py) to scraper module.
"""
from scrapers import tee_on, clubhouse_online, prophetservices, cps_golf, chronogolf, teeitup, teeon_portal, belacres

SCRAPERS = {
    "tee_on":             tee_on.scrape,
    "clubhouse_online":   clubhouse_online.scrape,
    "prophetservices":    prophetservices.scrape,
    "cps_golf":           cps_golf.scrape,
    "cps_golf_belacres":  belacres.scrape,
    "chronogolf":         chronogolf.scrape,
    "teeitup":            teeitup.scrape,
    "teeon_portal":       teeon_portal.scrape,
}
