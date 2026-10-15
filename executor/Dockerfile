FROM python:3.12-slim
RUN pip install --no-cache-dir paper-xlsx==0.2.2 paper-docx==0.2.1 paper-pptx==0.2.1 pandas==2.2.3 pypdf==6.1.1 reportlab==4.4.4
COPY runner.py /opt/runner.py
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python", "-I", "/opt/runner.py"]
