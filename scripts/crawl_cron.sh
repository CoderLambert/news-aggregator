#!/bin/bash
cd /root/news-aggregator/backend
/usr/bin/python3.14 manage.py crawl all >> /root/news-aggregator/logs/crawl.log 2>&1
