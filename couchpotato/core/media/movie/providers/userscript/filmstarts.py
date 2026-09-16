from bs4 import BeautifulSoup
from couchpotato.core.media._base.providers.userscript.base import UserscriptBase
import re

autoload = 'Filmstarts'


class Filmstarts(UserscriptBase):

	includes = ['*://www.filmstarts.de/kritiken/*']

	def getMovie(self, url):
		try:
			data = self.getUrl(url)
		except Exception:
			return

		html = BeautifulSoup(data, 'lxml')
		table = html.find("section", attrs={"class": "section ovw ovw-synopsis", "id": "synopsis-details"})
		if not table:
			return

		original_title = table.find("span", string=re.compile("Originaltitel"))
		if original_title: #some trailing whitespaces on some pages
			# Get original film title from the table specified above
			title = original_title.find_next('h2')
			if not title or table not in title.parents:
				return
			name = title.text
		else:
			# If none is available get the title from the meta data
			title = html.find("meta", {"property":"og:title"})
			if not title or not title.get('content'):
				return
			name = title['content']

		# Year of production is not available in the meta data, so get it from the table
		year_label = table.find("span", string=re.compile("Produktionsjahr"))
		year_value = year_label.find_next('span') if year_label else None
		if not year_value or table not in year_value.parents:
			return
		year = year_value.text

		return self.search(name, year)
