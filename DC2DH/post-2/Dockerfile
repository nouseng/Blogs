FROM python:3.11-slim
WORKDIR /app
# No build toolchain: the committed FMU ships a prebuilt linux64 CVODE binary
# (plus its SUNDIALS libs), so fmpy loads it directly with no runtime compile.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY contracts/ contracts/
COPY orchestrator/ orchestrator/
COPY gateway/ gateway/
COPY console/ console/
COPY modelica/DataCenterHeatRecovery/StockholmPod.fmu modelica/DataCenterHeatRecovery/StockholmPod.fmu
