"""Isolated stdlib-only SQL worker. No application imports, credentials or file database."""

import json
import math
import os
import sqlite3
import sys
import time

FUNCTIONS = {
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "coalesce",
    "ifnull",
    "nullif",
    "abs",
    "round",
    "lower",
    "upper",
    "length",
    "trim",
    "ltrim",
    "rtrim",
    "typeof",
}


def restrict_process():
    if os.name != "nt":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (192 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        return None

    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working", ctypes.c_size_t),
            ("max_working", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IO(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "read_ops",
                "write_ops",
                "other_ops",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", IO),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    # PROCESS_TIME | ACTIVE_PROCESS | PROCESS_MEMORY | KILL_ON_JOB_CLOSE
    limits.basic.flags = 0x2 | 0x8 | 0x100 | 0x2000
    limits.basic.process_time = 2 * 10000000
    limits.basic.active_processes = 1
    limits.process_memory = 192 * 1024 * 1024
    if (
        not job
        or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
        or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())
    ):
        raise RuntimeError("Cannot apply process resource limits")
    return job  # Keep the handle alive until process exit.


def authorize(action, arg1, arg2, database_name, trigger):
    if action == sqlite3.SQLITE_SELECT or action == sqlite3.SQLITE_RECURSIVE:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        # SQLite may authorize COUNT/aggregate table scans without a column/database name.
        if database_name in {"main", None} and arg1 in {"customers", "orders"}:
            return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def run(payload):
    process_limit_handle = restrict_process()
    connection = sqlite3.connect(":memory:")
    try:
        connection.enable_load_extension(False)
        connection.executescript(
            "CREATE TABLE customers(id INTEGER PRIMARY KEY,name TEXT NOT NULL);"
            "CREATE TABLE orders(id INTEGER PRIMARY KEY,customer_id INTEGER,"
            "amount_cents INTEGER,status TEXT);"
        )
        connection.executemany("INSERT INTO customers VALUES (?,?)", payload["customers"])
        connection.executemany("INSERT INTO orders VALUES (?,?,?,?)", payload["orders"])
        connection.commit()
        connection.execute("PRAGMA query_only=ON")
        for category, limit in (
            (sqlite3.SQLITE_LIMIT_LENGTH, 64000),
            (sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16000),
            (sqlite3.SQLITE_LIMIT_COLUMN, 32),
            (sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 40),
            (sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 10),
            (sqlite3.SQLITE_LIMIT_ATTACHED, 0),
            (sqlite3.SQLITE_LIMIT_FUNCTION_ARG, 16),
        ):
            connection.setlimit(category, limit)
        deadline = time.monotonic() + payload["timeout"]
        calls = 0

        def progress():
            nonlocal calls
            calls += 1
            return int(calls * 1000 > payload["max_steps"] or time.monotonic() > deadline)

        connection.set_progress_handler(progress, 1000)
        connection.set_authorizer(authorize)
        cursor = connection.execute(payload["sql"])
        rows = cursor.fetchmany(payload["max_rows"] + 1)
        if len(rows) > payload["max_rows"]:
            return {"code": "result_limit", "rows": []}
        # Avoid bytes/nonfinite output and never return raw SQLite errors or submitted SQL.
        if any(
            isinstance(value, bytes) or (isinstance(value, float) and not math.isfinite(value))
            for row in rows
            for value in row
        ):
            return {"code": "invalid_result", "rows": []}
        return {
            "code": "ok",
            "rows": rows,
            "limits_applied": process_limit_handle is not None or os.name != "nt",
        }
    except sqlite3.Error as exc:
        if "interrupted" in str(exc).lower():
            return {"code": "execution_timeout", "rows": []}
        return {"code": "invalid_or_forbidden_sql", "rows": []}
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(20000))
        result = run(request)
        encoded = json.dumps(result, ensure_ascii=True, allow_nan=False)
    except Exception:
        encoded = '{"code":"sandbox_unavailable","rows":[]}'
    sys.stdout.write(encoded)
