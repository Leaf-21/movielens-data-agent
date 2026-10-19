# -*- coding: utf-8 -*-
"""分类算法工具包（成员A，迭代二）。

对外入口：
- ``predict.classify(user_id, movie_id, prediction_time=None, algorithm=None)``
  供 Agent（成员B）进程内调用；
- ``train.py`` / ``predict.py`` 命令行入口，供独立运行与复现。
"""
