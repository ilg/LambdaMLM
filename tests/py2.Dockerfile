# Python 2.7 environment for running the test suite.
# Built and used by scripts/test-py2.
FROM python:2.7
ENV PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /deps/requirements.txt
COPY tests/requirements-py2.txt tests/constraints-py2.txt /deps/tests/
RUN pip install --no-cache-dir -r /deps/tests/requirements-py2.txt -c /deps/tests/constraints-py2.txt
