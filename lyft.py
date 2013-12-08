import getpass
import imaplib, email
import json
import matplotlib.pyplot as plt
import numpy as np
import re
import sqlite3

from datetime import datetime
from googlemaps import GoogleMaps
from time import mktime, strptime, struct_time

class Receipt:
	def __init__(self, message):
		for part in message.walk():
			if part.get_content_type() == 'text/plain':
				self.year = email.utils.parsedate_tz(message['Date'])[0]
				self.email_text = part.get_payload()

  	def sanitized_text(self):
  		dirty_strings = ['=20', '=0A', '*']
  		temp_string = self.email_text
  		for s in dirty_strings:
  			temp_string = temp_string.replace(s, ' ')

  		return ' '.join(temp_string.replace('=\r\n', '').split())

  	def check_special_addresses(self, s):
  		if s.find('Airport Access Rd, CA') != -1: # this address incorrectly maps to Oakland Airport
			return 'San Francisco International Airport'
		else:
			return s.replace('Unnamed Road,', '').replace('International Terminal Departures', '') # google maps cannot parse this address correctly

  	def get_start_location(self):
  		raw_start_loc = re.search('P\s?i\s?c\s?k\s?u\s?p(.*):(.*)D\s?r\s?o\s?p\s?o\s?f\s?f', self.sanitized_text())
  		try:
			return self.check_special_addresses(raw_start_loc.group(2).strip())
		except ValueError:
			return 'Bad start address string!'

  	def get_end_location(self):
  		raw_end_loc = re.search('D\s?r\s?o\s?p\s?o\s?f\s?f(.*):(.*)(USA|Lyft ride|Donation given|Donation:)', self.sanitized_text())
  		try:
			return self.check_special_addresses(raw_end_loc.group(2).strip())
		except ValueError:
			return 'Bad end address string!'

  	def get_bonus(self):
  		raw_bonus = re.search('Lyft Credits applied: - \$(.*) Card', self.sanitized_text())
  		return int(float(raw_bonus.group(1))) if raw_bonus is not None else 0;

  	def get_time(self):
  		'''
			Example 1: "Ride completed on September 22, 2012 at 7:02 PM Your Driver"
			Example 2: "Ride completed on November 25 at 10:07 AM Your Driver"
			Example 3: "Ride completed on December 13, 2012 Your Driver"
		'''

		## special hardcoded cases where timestamps are missing
		if self.sanitized_text().find('Receipt #1013515411') != -1:
			return datetime(2012, 12, 13, 10, 0, 0)
		elif self.sanitized_text().find('Receipt #1381856898') != -1:
			return datetime(2012, 12, 15, 10, 0, 0)
		elif self.sanitized_text().find('Receipt #1738191832') != -1:
			return datetime(2012, 12, 16, 1, 0, 0)
		elif self.sanitized_text().find('Receipt #1528835456') != -1:
			return datetime(2012, 12, 16, 13, 0, 0)

		## otherwise normal processing
		raw_date = re.search("Ride completed on (.*) Your Driver", self.sanitized_text())
		if raw_date is not None:
			raw_date_final = raw_date.group(1)
			temp = " ".join(raw_date_final.replace("at"," ").strip().split())

			## append year if not already there
			if temp.find('2012') == -1:
				temp = str(self.year) + ' ' + temp

			## try parsing with both formats
			try:
				t_struct1 = strptime(temp, '%Y %B %d %I:%M %p')
			except ValueError:
				t_struct1 = 'bad date string!'
			try:
				t_struct2 = strptime(temp, '%B %d, %Y %I:%M %p')
			except ValueError:
				t_struct2 = 'bad date string!'

			## return the appropriate struct
			t_struct = t_struct1 if type(t_struct1) is struct_time else t_struct2

		return datetime.fromtimestamp(mktime(t_struct))

  	def get_price(self):
		'''
			Example 1: "Donation:"
			Example 2: "Donation given to Tory:"
			Example 3: "Lyft ride charges:"
		'''

		case1 = re.search('Donation( given)? to ([\.\s\w]+): \$(\d+\.\d+)( Lyft Credits applied:\s\-\s\$\d+\.\d+)? Card ending with', self.sanitized_text())
		case2 = re.search('Lyft ride charges: \$(.*)(Card ending with|Lyft Credits)', self.sanitized_text())
		case3 = re.search('Donation: \$(.*) Total', self.sanitized_text())

		if case1 is not None:
			return int(float(case1.group(3)))
		elif case2 is not None:
			return int(float(case2.group(1)))
		elif case3 is not None:
			return int(float(case3.group(1)))

	def to_ride(self):
  		return Ride(self.get_start_location(), self.get_end_location(), self.get_time(), self.get_price(), self.get_bonus())

class Ride:
	def __init__(self, loc_start, loc_end, time, price, bonus):
		self.loc_start = loc_start
		self.loc_end = loc_end
		self.coordinates_start = None
		self.coordinates_end = None
		self.time = time
		self.price = price
		self.bonus = bonus
		self.google_payload = None
		self.distance = None

	def to_string(self):
		s = 'Start: %(loc_start)s\nEnd: %(loc_end)s\nTime: %(time)s\nPrice: %(price)d\nBonus: %(bonus)d\nDistance: %(distance)d' % \
		{"loc_start": self.loc_start, "loc_end": self.loc_end, "time": self.time, "price": self.price, "bonus": self.bonus, "distance": self.distance}
		return s

	def set_distance(self, GMAPS):
		if not self.loc_start or not self.loc_end:
			self.distance = 0
		else:
			self.set_gmaps_data(GMAPS.directions(self.loc_start, self.loc_end))
		return self

	def set_gmaps_data(self, payload):
		self.google_payload = payload
		self.distance = payload["Directions"]["Distance"]["meters"]
		self.loc_start = payload["Placemark"][0]["address"]
		self.loc_end = payload["Placemark"][1]["address"]
		self.coordinates_start = payload["Placemark"][0]["Point"]["coordinates"]
		self.coordinates_end = payload["Placemark"][1]["Point"]["coordinates"]
		return self

def main():
	# connect to gmail server
	print 'connecting to gmail server...'
	username = raw_input("Gmail username: ")
	pw = getpass.getpass()
	mail = connect_to_gmail(username, pw)
	print 'done.'

	# fetch the relevant receipts
	print 'fetching lyft receipts...'
	receipts = fetch_receipts(mail, directory='Subscriptions')
	print 'done.'

	# parse ride data, grabbing distances from google maps
	print 'grabbing distances...'
	GOOGLE_API_KEY = open("google_maps_key.txt", "r").read()
	GMAPS = GoogleMaps(GOOGLE_API_KEY)
	rides = []
	for receipt in receipts:
		ride = receipt.to_ride().set_distance(GMAPS)
		rides.append(ride)

	print 'done.'

	# put data in array, insert into database
	print 'filling database...'
	data = [(r.distance, r.price, r.bonus, r.time) for r in rides]
	conn = build_db(data)
	print 'done.'

	# query for results
	print 'running queries...'
	results = run_queries(conn)
	print 'done.'

	# plot charts
	print 'plotting charts...'
	plt = plot_data(results)
	plt.show()
	print 'done.'

	# dump coordinates data to json file
	print 'exporting coordinates...'
	export = export_coordinates(rides)
	print 'done.'

def connect_to_gmail(username, password):
	mail = imaplib.IMAP4_SSL('imap.gmail.com', '993')
	mail.login(username, password)

	return mail

def fetch_receipts(mail, directory='All Mail', search_type='Subject', search_text='Lyft Ride Receipt'):
	mail.select(directory)
	response, message_ids = mail.uid('search', None, '(HEADER %(search_type)s "%(search_text)s")' % \
		{"search_type": "Subject", "search_text": "Lyft Ride Receipt"})
	receipts = []

	for num in message_ids[0].split():
	    typ, data = mail.uid('fetch', num, '(RFC822)')
	    msg = email.message_from_string(data[0][1])
	    receipts.append(Receipt(msg))

	return receipts

def build_db(data):
	conn = sqlite3.connect('lyft.db')
	c = conn.cursor()

	# drop table if exists
	table_exists = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rides';").fetchall()
	if table_exists:
		c.execute("DROP TABLE rides;")
	
	# create table with given fields
	c.execute("CREATE TABLE rides (distance integer, price integer, bonus integer, time text);")

	# insert data
	c.executemany("INSERT INTO rides VALUES (?,?,?,?);", data)

	conn.commit()
	return conn

def run_queries(conn):
	results = {}
	c = conn.cursor()

	c.execute("SELECT SUM(price), SUM(distance), COUNT(*), AVG(price), AVG(distance), 1.0 * SUM(price)/SUM(distance) FROM rides;")
	r = c.fetchone()
	# print r.keys()
	results["totals"] = r

	# aggregates by month
	c.execute("SELECT STRFTIME('%Y-%m', time) AS MONTH, COUNT(*), SUM(distance), SUM(price), AVG(price), AVG(distance), 1.0 * SUM(price)/SUM(distance) FROM rides GROUP BY MONTH;")
	results['by_month'] = np.array(c.fetchall(), dtype=[('month', np.str_, 16), ('num_rides', int), ('total_distance', int), ('total_cost', int), ('avg_cost', float), ('avg_distance', float), ('dollars_per_meter', float)])

	# aggregates by day
	c.execute("SELECT STRFTIME('%Y-%m-%d', time) AS DAY, COUNT(*), SUM(distance), SUM(price), AVG(price), AVG(distance), 1.0 * SUM(price)/SUM(distance) FROM rides GROUP BY DAY;")
	results['by_day'] = np.array(c.fetchall(), dtype=[('day', np.str_, 16), ('num_rides', int), ('total_distance', int), ('total_cost', int), ('avg_cost', float), ('avg_distance', float), ('dollars_per_meter', float)])

	# aggregates by hour
	c.execute("SELECT STRFTIME('%H', time) AS HOUR, COUNT(*), SUM(distance), SUM(price), AVG(price), AVG(distance), 1.0 * SUM(price)/SUM(distance) FROM rides GROUP BY HOUR;")
	results["by_hour"] = np.array(c.fetchall(), dtype=[('hour', np.str_, 16), ('num_rides', int), ('total_distance', int), ('total_cost', int), ('avg_cost', float), ('avg_distance', float), ('dollars_per_meter', float)])

	# aggregates by day of week
	c.execute("SELECT STRFTIME('%w', time) AS DAY_OF_WEEK, COUNT(*), SUM(distance), SUM(price), AVG(price), AVG(distance), 1.0 * SUM(price)/SUM(distance) FROM rides GROUP BY DAY_OF_WEEK;")
	results['by_day_of_week'] = np.array(c.fetchall(), dtype=[('day_of_week', np.str_, 16), ('num_rides', int), ('total_distance', int), ('total_cost', int), ('avg_cost', float), ('avg_distance', float), ('dollars_per_meter', float)])

	# entire table (by record), excluding where distances = 0
	c.execute("SELECT * FROM rides WHERE distance != 0;")
	results['by_record'] = np.array(c.fetchall(), dtype=[('distance', int), ('price', int), ('bonus', int), ('time', np.str_, 16)])

	return results

def plot_data(results):
	# by month
	fig = plt.figure()
	plt.title('Lyft Rides by Month')
	plt.xlabel('Month')
	plt.ylabel('Number of Rides')
	ax = fig.add_subplot(1, 1, 1)
	ax.xaxis_date()
	plt.bar([datetime.strptime(d, '%Y-%m') for d in results['by_month']['month']], results['by_month']['num_rides'], alpha=0.4, width=25)
	plt.xticks(rotation=50)
	plt.savefig('./by_month.png')

	# distribution of days by number rides
	plt.figure()
	plt.hist(results['by_day']['num_rides'], bins=[0, 1, 2, 3, 4, 5], normed=True, alpha=0.4)

	# distribution of rides by day of week
	plt.figure()
	days_of_week = map(int, results['by_day_of_week']['day_of_week'])
	plt.bar(days_of_week, results['by_day_of_week']['num_rides'], align='center', alpha=0.4)
	plt.xlabel('Day of Week')
	plt.ylabel('Number of Rides')
	plt.xticks(days_of_week, ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'], rotation=50)
	plt.savefig('./by_day_of_week.png')

	# distribution of rides by hour
	plt.figure()
	hours = map(int, results['by_hour']['hour'])
	plt.bar(hours, results['by_hour']['num_rides'], align='center', alpha=0.4)
	plt.xlabel('Hour')
	plt.ylabel('Number of Rides')
	plt.xlim(0, 23)
	plt.savefig('./by_hour.png')

	# price as function of distance
	plt.figure()
	plt.scatter(results['by_record']['distance'] / 1600.0, results['by_record']['price'], alpha=0.4)
	plt.xlabel('Distance (miles)')
	plt.ylabel('Price (dollars)')
	plt.xlim(0, 25)
	plt.savefig('./price_by_distance.png')

	return plt

def export_coordinates(rides):
	coordinates = []
	for ride in rides:
		if ride.coordinates_start and ride.coordinates_end:
			coordinates.append({"start": ride.coordinates_start[0:2][::-1], "end": ride.coordinates_end[0:2][::-1]})

	with open('coordinates.json', 'w') as outfile:
		json.dump(coordinates, outfile)

	return outfile

if __name__ == "__main__":
    main()