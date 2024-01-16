function FindProxyForURL(url, host)
{
//
//Exclude FTP from proxy
//
if (url.substring(0, 4) == "ftp:")
{
return "DIRECT";
}
if (dnsDomainIs(host,"api.github.com"))
{
return "PROXY 10.37.129.2:8080; PROXY 10.0.2.2:8080";
}
if (dnsDomainIs(host,"google.com"))
{
return "PROXY 127.0.0.1:8080";
}
return "DIRECT";
}
