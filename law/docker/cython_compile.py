"""
Cython 컴파일 스크립트
app/ 하위의 모든 .py 파일 (단, __init__.py 제외)을 .so로 컴파일한다.
gcc segfault(QEMU 에뮬레이션) 대응: -O0, 실패 시 2회 재시도, 그래도 실패하면 .py 유지(skip)
"""
import os
import subprocess
import sys
import sysconfig

ext = sysconfig.get_config_var('EXT_SUFFIX')  # .cpython-312-x86_64-linux-gnu.so
include = sysconfig.get_path('include')

py_files = []
for root, dirs, files in os.walk('app'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in files:
        if f.endswith('.py') and f != '__init__.py':
            py_files.append(os.path.join(root, f))

print(f'컴파일 대상: {len(py_files)}개 파일', flush=True)

success_count = 0
skip_count = 0

for py_file in sorted(py_files):
    name = py_file[:-3]  # .py 제거
    c_file = name + '.c'
    so_file = name + ext

    # .py → .c (Cython)
    result = subprocess.run(
        [sys.executable, '-m', 'cython', '--3str', py_file],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f'Cython 실패: {py_file}\n{result.stderr}', file=sys.stderr, flush=True)
        sys.exit(1)

    # .c → .so (gcc) — 실패 시 재시도 1회, 그래도 실패하면 skip
    compiled = False
    for attempt in range(2):
        result = subprocess.run([
            'gcc', '-shared', '-fPIC', '-O0',  # -O2 → -O0 (QEMU 안정성)
            f'-I{include}',
            '-o', so_file, c_file
        ], capture_output=True, text=True)
        if result.returncode == 0:
            compiled = True
            break
        print(f'  gcc 재시도 {attempt + 1}/2: {py_file}\n{result.stderr}', flush=True)

    if compiled:
        os.remove(py_file)
        os.remove(c_file)
        print(f'  compiled: {so_file}', flush=True)
        success_count += 1
    else:
        # .py 유지 (컴파일 실패) — gcc segfault 등 QEMU 불안정 시
        if os.path.exists(c_file):
            os.remove(c_file)
        if os.path.exists(so_file):
            os.remove(so_file)
        print(f'  SKIP (gcc 실패): {py_file} — .py 유지', flush=True)
        skip_count += 1

print(f'컴파일 완료: {success_count}개 성공, {skip_count}개 skip', flush=True)
if skip_count > 0:
    print(f'WARNING: {skip_count}개 파일이 .py로 남아있습니다', flush=True)
