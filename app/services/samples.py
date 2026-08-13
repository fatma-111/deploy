"""Benchmark bugs used for demos, manual QA and the evaluation harness."""

from __future__ import annotations

SAMPLES = [
    {
        "id": "langchain-import",
        "label": "LangChain — moved import",
        "language": "Python",
        "framework": "LangChain",
        "error_message": "ModuleNotFoundError: No module named 'langchain.chat_models'",
        "stack_trace": (
            'Traceback (most recent call last):\n'
            '  File "app/main.py", line 3, in <module>\n'
            '    from langchain.chat_models import ChatOpenAI\n'
            "ModuleNotFoundError: No module named 'langchain.chat_models'"
        ),
        "source_code": "from langchain.chat_models import ChatOpenAI\n\nllm = ChatOpenAI(model='gpt-4o-mini')\n",
        "dependencies": ["langchain==0.3.7", "langchain-openai==0.2.5"],
        "logs": "",
        "repository_url": "https://github.com/langchain-ai/langchain",
    },
    {
        "id": "fastapi-422",
        "label": "FastAPI — 422 validation",
        "language": "Python",
        "framework": "FastAPI",
        "error_message": (
            "422 Unprocessable Entity: {'detail': [{'type': 'missing', "
            "'loc': ['body', 'email'], 'msg': 'Field required'}]}"
        ),
        "stack_trace": "",
        "source_code": (
            "from fastapi import FastAPI\n"
            "from pydantic import BaseModel\n\n"
            "app = FastAPI()\n\n"
            "class User(BaseModel):\n"
            "    name: str\n"
            "    email: str\n\n"
            "@app.post('/users')\n"
            "def create_user(user: User):\n"
            "    return user\n"
        ),
        "dependencies": ["fastapi==0.115.0", "pydantic==2.9.2"],
        "logs": 'INFO: 127.0.0.1 - "POST /users HTTP/1.1" 422 Unprocessable Entity',
        "repository_url": "https://github.com/fastapi/fastapi",
    },
    {
        "id": "node-module",
        "label": "Node.js — missing module",
        "language": "JavaScript",
        "framework": "Express",
        "error_message": "Error: Cannot find module 'express'",
        "stack_trace": (
            "Error: Cannot find module 'express'\n"
            "    at Function.Module._resolveFilename (node:internal/modules/cjs/loader:1145:15)\n"
            "    at Object.<anonymous> (/app/server.js:1:17)"
        ),
        "source_code": "const express = require('express');\nconst app = express();\napp.listen(3000);\n",
        "dependencies": ["express@^4.19.2"],
        "logs": "npm ERR! code MODULE_NOT_FOUND",
        "repository_url": "https://github.com/expressjs/express",
    },
    {
        "id": "python-keyerror",
        "label": "Python — KeyError in handler",
        "language": "Python",
        "framework": "Flask",
        "error_message": "KeyError: 'user_id'",
        "stack_trace": (
            'Traceback (most recent call last):\n'
            '  File "app/handlers.py", line 42, in get_profile\n'
            "    user_id = payload['user_id']\n"
            "KeyError: 'user_id'"
        ),
        "source_code": (
            "def get_profile(payload):\n"
            "    user_id = payload['user_id']\n"
            "    return db_lookup(user_id)\n"
        ),
        "dependencies": ["flask==3.0.3"],
        "logs": "2026-08-13 10:22:11 ERROR handlers KeyError raised for POST /profile",
        "repository_url": "",
    },
]

SAMPLES_BY_ID = {s["id"]: s for s in SAMPLES}
