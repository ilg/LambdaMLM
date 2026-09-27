# Python environment for running the test suite, matching the Lambda runtime's
# Python version.  Built and used by scripts/test.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore
COPY lambda/requirements.txt /deps/lambda/requirements.txt
COPY tests/requirements.txt /deps/tests/requirements.txt
RUN pip install --no-cache-dir -r /deps/tests/requirements.txt
