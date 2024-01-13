#!/usr/bin/env bash

echo "downloading FOP"

fop_ver="2.9"

fop_name="fop-$fop_ver-bin.tar.gz"
fop_url="https://www.apache.org/dyn/closer.cgi?filename=/xmlgraphics/fop/binaries/$fop_name&action=download"

curl -fLo $fop_name "$fop_url"

fop_sha=$(sha512sum $fop_name | cut -f 1 -d " ")

sha_name="fop-$fop_ver-bin.tar.gz.sha512"
sha_url="https://downloads.apache.org/xmlgraphics/fop/binaries//$sha_name"

curl -fLo $sha_name "$sha_url"

sha=$(cat $sha_name | cut -f 1 -d " ")

if [ "$sha" != "$fop_sha" ]; then
  echo "fop sha failed"
  echo "$sha != $fop_sha"
  exit 1
fi

echo
echo "downloading FOP sandbox"

sb_name="fop-sandbox-$fop_ver.jar"
sb_url="https://repo1.maven.org/maven2/org/apache/xmlgraphics/fop-sandbox/$fop_ver/$sb_name"

curl -fLo $sb_name "$sb_url"

sb_sha=$(sha512sum $sb_name | cut -f 1 -d " ")

sb_sha_name="fop-sandbox-$fop_ver.jar.sha512"
sb_sha_url="https://repo1.maven.org/maven2/org/apache/xmlgraphics/fop-sandbox/$fop_ver/$sb_sha_name"

curl -fLo $sb_sha_name "$sb_sha_url"

sha=$(cat $sb_sha_name)

if [ "$sha" != "$sb_sha" ]; then
  echo "sandbox sha failed"
  echo "$sha != $sb_sha"
  exit 1
fi

echo
echo "downloading FOP hyphenation"

hyph_name="fop-hyph-2.0.jar"
hyph_url="https://repo1.maven.org/maven2/net/sf/offo/fop-hyph/2.0/$hyph_name"

curl -fLo $hyph_name "$hyph_url"

hyph_sha=$(sha1sum $hyph_name | cut -f 1 -d " ")

hyph_sha_name="fop-hyph-2.0.jar.sha1"
hyph_sha_url="https://repo1.maven.org/maven2/net/sf/offo/fop-hyph/2.0/$hyph_sha_name"

curl -fLo $hyph_sha_name "$hyph_sha_url"

sha=$(cat $hyph_sha_name)

if [ "$sha" != "$hyph_sha" ]; then
  echo "hyph sha failed"
  echo "$sha != $hyph_sha"
  exit 1
fi

tar -xf $fop_name

mv $sb_name "fop-$fop_ver/fop/build/fop-sandbox.jar"

mv $hyph_name "fop-$fop_ver/fop/build/fop-hyph.jar"

rm $fop_name
rm $sha_name
rm $sb_sha_name
rm $hyph_sha_name

echo
echo "SUCCESS"
