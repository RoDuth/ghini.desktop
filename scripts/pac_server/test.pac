function FindProxyForURL(url, host)
{
//
//Exclude FTP from proxy
//
if (url.substring(0, 4) == "ftp:")
{
return "DIRECT";
}
//
//Bypass proxy for internal hosts
//
if (isInNet(host, "0.0.0.0", "255.0.0.0")||
isInNet(host, "10.0.0.0", "255.0.0.0") ||
isInNet(host, "127.0.0.0", "255.0.0.0") ||
isInNet(host, "169.254.0.0", "255.255.0.0") ||
isInNet(host, "172.16.0.0", "255.240.0.0") ||
isInNet(host, "192.0.2.0", "255.255.255.0")||
isInNet(host, "64.206.157.136", "255.255.255.255"))
{
return "DIRECT";
}
//
//Bypass proxy for this server
//
if (dnsDomainIs(host, "mail.domain.com"))
{
return "DIRECT";
}
return "DIRECT";
}
