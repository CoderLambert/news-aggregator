#!/bin/bash
cd /root/news-aggregator/backend
/usr/bin/python3.14 manage.py crawl all >> /root/news-aggregator/logs/crawl.log 2>&1

# 确保Django服务在运行
if ! pgrep -f "runserver.*9527" > /dev/null; then
    /usr/bin/python3.14 manage.py runserver 0.0.0.0:9527 >> /root/news-aggregator/logs/django.log 2>&1 &
fi
