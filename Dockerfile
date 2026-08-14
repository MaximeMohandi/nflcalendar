FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 nflcalendar
COPY nfl_calendar ./nfl_calendar
USER nflcalendar
EXPOSE 8000
CMD ["python", "-m", "nfl_calendar.server"]
