#!/bin/bash
cd /root/news-aggregator/backend
python3 manage.py crawl all >> /root/news-aggregator/logs/crawl.log 2>&1
