"""Public marketing WSGI, structured data and E-E-A-T honesty regression."""
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
import json
import os
import re
import unittest
import xml.etree.ElementTree as ET

from greengrapeme.marketing_site import (
    FAQ, PAGES, PublicSiteConfig, create_marketing_app,
    create_marketing_service_from_env,
)


ORIGIN = "https://green.example.org"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag in ("a", "link"):
            values = dict(attrs)
            href = values.get("href")
            if href:
                self.links.append(href)


class PublicLandingPageTests(unittest.TestCase):
    def setUp(self):
        self.config = PublicSiteConfig(
            origin=ORIGIN,
            operator_name="Example & Partner GmbH",
            contact_email="kontakt@example.org",
            imprint_url=ORIGIN+"/impressum",
            privacy_url=ORIGIN+"/datenschutz",
            app_url="https://app.example.org/",
        )
        self.app = create_marketing_app(self.config)

    def request(self,path="/",method="GET",scheme="https",headers=None):
        env={
            "REQUEST_METHOD":method,
            "PATH_INFO":path,
            "wsgi.url_scheme":scheme,
            "wsgi.input":BytesIO(b""),
        }
        setup_testing_defaults(env)
        env.update(headers or {})
        response={}
        def start(status,values):
            response["status"]=status
            response["headers"]=dict(values)
        response["body"]=b"".join(self.app(env,start))
        return response

    def test_every_product_page_is_indexable_unique_and_has_real_content(self):
        self.assertGreaterEqual(len(PAGES),10)
        seen_titles=set()
        seen_descriptions=set()
        for path,page in PAGES.items():
            with self.subTest(path=path):
                response=self.request(path)
                self.assertEqual(response["status"],"200 OK")
                headers=response["headers"]
                self.assertEqual(headers["Content-Language"],"de-DE")
                self.assertEqual(headers["X-Content-Type-Options"],"nosniff")
                self.assertIn("script-src 'none'",headers["Content-Security-Policy"])
                self.assertNotIn("X-Robots-Tag",headers)
                self.assertEqual(headers["Content-Length"],str(len(response["body"])))
                html=response["body"].decode("utf-8")
                self.assertIn('<html lang="de">',html)
                self.assertIn('<main id="inhalt">',html)
                self.assertIn("<h1>",html)
                self.assertIn(
                    '<link rel="canonical" href="'+ORIGIN+path+'">',html)
                self.assertIn(
                    '<meta name="description" content=',html)
                self.assertIn('<meta name="robots" content="index,follow',html)
                self.assertIn('aria-label="Hauptnavigation"',html)
                self.assertIn("Example &amp; Partner GmbH",html)
                self.assertIn("Impressum",html)
                self.assertIn("Datenschutz",html)
                self.assertIn("Pilotprojekt anfragen",html)
                self.assertIn("schema.org",html)
                self.assertNotIn("Google Analytics",html)
                self.assertNotIn("fonts.googleapis.com",html)
                self.assertNotIn("AggregateRating",html)
                self.assertNotIn('"review":',html)
                self.assertNotIn('"price":',html)
                title=re.search(r"<title>(.*?)</title>",html).group(1)
                description=re.search(
                    r'<meta name="description" content="(.*?)">',html).group(1)
                self.assertNotIn(title,seen_titles)
                self.assertNotIn(description,seen_descriptions)
                seen_titles.add(title)
                seen_descriptions.add(description)
                # Long-form, non-templated content - not empty doorway pages.
                prose=re.sub(r"<[^>]*>"," ",html)
                self.assertGreater(len(prose.split()),110)
                links=Links()
                links.feed(html)
                for href in links.links:
                    if href.startswith("/"):
                        self.assertTrue(
                            href in PAGES or href in ("/app.css","/marketing.css"),
                            (path,href))

    def test_schema_org_matches_visible_content_and_avoids_fake_rich_results(self):
        for path,page in PAGES.items():
            with self.subTest(path=path):
                html=self.request(path)["body"].decode("utf-8")
                script=re.search(
                    r'<script type="application/ld\+json">(.*?)</script>',
                    html,re.S)
                self.assertIsNotNone(script)
                graph=json.loads(unescape(script.group(1)))["@graph"]
                types={item["@type"] for item in graph}
                self.assertIn("Organization",types)
                self.assertIn("WebSite",types)
                self.assertIn("WebPage",types)
                organisation=next(x for x in graph
                                  if x["@type"]=="Organization")
                self.assertEqual(organisation["name"],self.config.operator_name)
                self.assertEqual(organisation["email"],self.config.contact_email)
                self.assertIn(self.config.operator_name.replace("&","&amp;"),
                              html)
                webpage=next(x for x in graph if x["@type"]=="WebPage")
                self.assertEqual(webpage["url"],ORIGIN+path)
                self.assertEqual(webpage["description"],page.description)
                self.assertIn(page.heading,html)
                if path == "/":
                    self.assertIn("SoftwareApplication",types)
                    self.assertNotIn("BreadcrumbList",types)
                else:
                    self.assertIn("BreadcrumbList",types)
                if path == "/fragen":
                    faq=next(x for x in graph if x["@type"]=="FAQPage")
                    self.assertEqual(len(faq["mainEntity"]),len(FAQ))
                    for question,answer in FAQ:
                        self.assertIn(question,html)
                        self.assertIn(answer,html)
                else:
                    self.assertNotIn("FAQPage",types)
                if path == "/vertriebsautomatisierung":
                    self.assertIn("Service",types)
                else:
                    self.assertNotIn("Service",types)
                self.assertFalse(types.intersection({
                    "AggregateRating","Review","Product","Offer"}))

    def test_sitemap_robots_index_separation_and_head(self):
        sitemap=self.request("/sitemap.xml")
        self.assertEqual(sitemap["status"],"200 OK")
        self.assertIn("application/xml",sitemap["headers"]["Content-Type"])
        root=ET.fromstring(sitemap["body"])
        ns={"sm":"http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls=[x.text for x in root.findall("sm:url/sm:loc",ns)]
        self.assertEqual(urls,[ORIGIN+path for path in PAGES])
        self.assertEqual(len(set(urls)),len(PAGES))
        self.assertNotIn(ORIGIN+"/api/me",urls)
        self.assertNotIn(ORIGIN+"/saas.js",urls)
        robots=self.request("/robots.txt")
        self.assertIn(b"Sitemap: "+ORIGIN.encode()+b"/sitemap.xml",
                      robots["body"])
        self.assertIn(b"Disallow: /api/",robots["body"])
        self.assertNotIn("X-Robots-Tag",
                         self.request("/")["headers"])
        for path in ("/","/lead-recherche","/sitemap.xml",
                     "/robots.txt","/marketing.css","/app.css"):
            with self.subTest(path=path):
                get=self.request(path)
                head=self.request(path,method="HEAD")
                self.assertEqual(head["status"],get["status"])
                self.assertEqual(head["headers"]["Content-Length"],
                                 str(len(get["body"])))
                self.assertEqual(head["body"],b"")
        self.assertIn("noindex",self.request("/marketing.css")[
            "headers"]["X-Robots-Tag"])

    def test_public_site_is_read_only_tls_only_and_never_exposes_saas(self):
        for path in ("/api/me","/saas.js","/public/config",
                     "/.env","/wp-admin","/robots.txt/../api/me"):
            response=self.request(path)
            self.assertTrue(response["status"].startswith("404"),path)
            self.assertIn("noindex",response["headers"]["X-Robots-Tag"])
        self.assertEqual(self.request("/",scheme="http")["status"],
                         "403 Forbidden")
        for method in ("POST","PUT","DELETE","PATCH"):
            response=self.request("/",method=method)
            self.assertEqual(response["status"],"405 Method Not Allowed")
        self.assertEqual(
            self.request("/",headers={
                "HTTP_X_FORWARDED_HOST":"evil.example",
                "HTTP_HOST":"attacker.example",
            })["body"],
            self.request("/")["body"],
        )
        self.assertNotIn(b"GG_PUBLIC_CONTACT_EMAIL",self.request("/")["body"])

    def test_no_unconfigured_operator_or_legal_identifiers_can_go_public(self):
        values=dict(
            origin=ORIGIN,operator_name="Example GmbH",
            contact_email="kontakt@example.org",
            imprint_url=ORIGIN+"/impressum",
            privacy_url=ORIGIN+"/datenschutz",
            app_url="https://app.example.org/")
        malicious={
            "origin":["http://green.example.org","https://user@green.example.org",
                      "https://green.example.org/path","https://green.example.org/",
                      "https://green.example.org:99999"],
            "operator_name":["","Acme <script>alert(1)</script>"],
            "contact_email":["","invalid","mailto:test@example.org"],
            "imprint_url":["","javascript:alert(1)","http://example.org/impressum"],
            "privacy_url":["","https://x.example.org/#fake"],
            "app_url":["","http://app.example.org/"],
        }
        for key,invalids in malicious.items():
            for bad in invalids:
                with self.subTest(key=key,bad=bad):
                    with self.assertRaises(ValueError):
                        PublicSiteConfig(**{**values,key:bad})
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(KeyError):
                create_marketing_service_from_env()

    def test_public_contact_page_never_collects_customer_secrets(self):
        content=self.request("/kontakt")["body"].decode()
        self.assertIn("mailto:kontakt@example.org",content)
        self.assertIn("Example &amp; Partner GmbH",content)
        self.assertNotIn("<form",content.lower())
        self.assertNotIn("login-button",content)
        self.assertNotIn('action="https://',content)


if __name__=="__main__":
    unittest.main()
