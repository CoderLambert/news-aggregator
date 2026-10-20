"""Run only from the named isolated RSSHub sandbox; public HTTP redirect probe."""
import os,json,socket,requests

def main():
    if os.environ.get('RSSHUB_LIVE')!='synthetic-isolated':raise RuntimeError('isolated opt-in required')
    proxy={'http':'http://rsshub-egress-proxy:3128','https':'http://rsshub-egress-proxy:3128'}
    results={}
    for name,url in [('loopback','http://127.0.0.1/'),('metadata','http://169.254.169.254/latest/meta-data/'),
        ('docker_private','http://192.168.1.1/'),('fakeip','http://198.18.0.28/'),('dns_private','http://localtest.me/'),
        ('ipv6','https://[::1]/'),('mapped_ipv6','https://[::ffff:127.0.0.1]/'),('decimal_loopback','http://2130706433/')]:
        try:
            response=requests.get(url,proxies=proxy,timeout=10)
            assert response.status_code==403,(name,response.status_code)
        except requests.exceptions.ProxyError as exc:
            assert '403' in str(exc),name
        results[name]='blocked_403'
    response=requests.get('https://httpbingo.org/redirect-to?url=http://127.0.0.1:8080/',proxies=proxy,timeout=15)
    assert response.status_code==403 and response.history and response.history[0].status_code in (301,302,303,307,308)
    results['redirect_private']='public_redirect_then_private_403'
    try:
        conn=socket.create_connection(('1.1.1.1',443),timeout=3);conn.close()
    except OSError:results['direct_bypass']='blocked'
    else:raise AssertionError('RSSHub sandbox has direct Internet route')
    response=requests.get('https://example.com/',proxies=proxy,timeout=15)
    assert response.status_code==200
    results['public_https']='200'
    print(json.dumps(results))
if __name__=='__main__':main()
