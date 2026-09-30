#!/usr/bin/env bash
# 探测 Hadoop 3.4.1 各镜像可用性与速度
for u in \
  https://mirrors.aliyun.com/apache/hadoop/common/hadoop-3.4.1/hadoop-3.4.1.tar.gz \
  https://mirrors.tuna.tsinghua.edu.cn/apache/hadoop/common/hadoop-3.4.1/hadoop-3.4.1.tar.gz \
  https://mirrors.bfsu.edu.cn/apache/hadoop/common/hadoop-3.4.1/hadoop-3.4.1.tar.gz \
  https://mirrors.nju.edu.cn/apache/hadoop/common/hadoop-3.4.1/hadoop-3.4.1.tar.gz \
  https://repo.huaweicloud.com/apache/hadoop/common/hadoop-3.4.1/hadoop-3.4.1.tar.gz \
  https://archive.apache.org/dist/hadoop/common/hadoop-3.4.1/hadoop-3.4.1.tar.gz
do
  r=$(curl -s -o /dev/null -w "%{http_code} speed=%{speed_download}" --max-time 20 -r 0-3145727 "$u" 2>/dev/null)
  echo "$r | $u"
done
