#!/bin/bash
/usr/bin/java -Xmx4g -DLOG_FILENAME="logs/logchecker" -Dlogback.configurationFile=logback.xml -jar ./CheckerChallenge-1.11.4.jar instances.csv
