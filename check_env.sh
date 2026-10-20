#!/bin/bash
cd /home/skywalker123/movielens-data-agent

echo "=== 1) 系统 python3.12 能否 import ==="
/usr/bin/python3.12 - <<'PY'
import sys
print("exe:", sys.executable)
try:
    import numpy
    print("numpy OK:", numpy.__version__, numpy.__file__)
except Exception as e:
    print("numpy FAIL:", type(e).__name__, e)
try:
    import sklearn
    print("sklearn OK:", sklearn.__version__)
except Exception as e:
    print("sklearn FAIL:", type(e).__name__, e)
PY

echo
echo "=== 2) 模拟 -I 隔离模式 ==="
/usr/bin/python3.12 -I - <<'PY'
import sys
try:
    import numpy
    print("numpy OK in -I:", numpy.__version__)
except Exception as e:
    print("numpy FAIL in -I:", type(e).__name__, e)
PY

echo
echo "=== 3) Agent 进程 80711 的环境变量 ==="
tr '\0' '\n' < /proc/80711/environ 2>/dev/null | grep -Ei 'python|path' | head -20

echo
echo "=== 4) 直接问 Agent 进程外，用其 exe 跑 run_fit ==="
/usr/bin/python3.12 -c "import numpy; print('direct ok', numpy.__version__)" 2>&1 | tail -3
