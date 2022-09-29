""" Goodreads extract owned book metadata

Requirements:
1. Data dump
2. Book export
3. Grab amazon books list and upload to {goodreads, system of choiuce)

Problems:
Owned book JSON export does not conain any metadata to join to books collection

"""
# importanized ...
import csv
import decimal
import re
import json
import os.path
import dataclasses
import os
from urllib.parse import urlparse
from typing import List, Optional, Callable, Any, Mapping
from copy import copy

import bs4
import requests
from bs4 import BeautifulSoup
from urllib.request import urlopen

import logging
log = logging.getLogger(__name__)
logging.basicConfig(level="DEBUG")

goodreads = "https://www.goodreads.com"
goodreads_user_url = f"{goodreads}/review/list"
goodreads_book_url = f"{goodreads}/book/show"



def filter_owned_books(books, owned):
    """The Goodreads data dump, which contains (among other things)
    the set of owned books with custom covers, condition, and purchase date.
    However, the "owned books" data does not contain a Book ID, and so we need
    to match titles to extract a BookId from an owned book in order to access
    those covers and condition data.

    ref: https://help.goodreads.com/s/article/Why-are-you-removing-details-about-owned-books

    Just append the BookId to the Book item.

    :param books: list(dict) Books
    :param owned_books: list(dict) OwnedBook (smaller than Book)
    :returns list(BookId)
    """
    owned_books = []

    """
    This can now be reduced to a call to `filter()`
    """

    for owned_book in owned:
        title = owned_book['book']

        try:
            ref = books[title]
        except KeyError:
            log.error(f"{title} not found")
            continue
        else:
            owned_books.append(copy(ref))

    return owned_books

def get_cover_image(book_id):
    url = os.path.join(goodreads_book_url, book_id)

    try:
        url_open = urlopen(url)
        soup = BeautifulSoup(url_open, 'html.parser')
        tag = soup.find("img", {"id": "coverImage"})
        img_src = tag['src']
        return img_src
    except:
        raise


class SoupyField:
    pass


class MappedSoupyField(SoupyField):
    map: Callable
    source: bs4.Tag
    value: Any

    def __init__(self, value: bs4.Tag):
        self.value = self.map(value)
        self.source = value

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value

    @staticmethod
    def map(tag: bs4.Tag):
        raise NotImplementedError()


class Shelves(MappedSoupyField):
    @staticmethod
    def map(tag):
        return tag.text.strip().split('\n')[-1]


class Cover(MappedSoupyField):
    """
    Goodreads image caching:
    <img alt= Stranger in a Strange Land" id="cover_review_491725315" src="https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/1156897088l/350._SY75_.jpg">
    ^ ^ the url https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/1156897088l/350._SY75_.jpg contains intsructions for returned image size: 75 px wide.
      /1156897088l/350._SY75_.jpg will return 75 px image (thumb)
      /1156897088l/350._SY475_.jpg will return 475 image ("enlarged" image)

    To get the original(nonresized), reformat and remove the cache suffixes `._SY{width}`, `._SX{height}`, or both.
      /1156897088l/350.jpg
    """
    @staticmethod
    def map(tag):
        img = tag.find('div', {'data-resource-type': 'Book'}).find('a').find('img')
        resized_img = img.attrs['src']

        # replace the resizing CDN path goodreads uses to get the original cover image
        compressed_img_re = r'S[X|Y][\d]+'
        matches = re.findall(f'{compressed_img_re}', resized_img)
        if matches:
            original_img = resized_img
            underscores = 1
            for match in matches:
                # strip out the resize identifier found
                original_img = re.sub(match, '', original_img)
                underscores += 1
            cruft = '.' + '_'*underscores
            original_img = re.sub(f"{cruft}", '', original_img)

            return original_img

        # nope.
        return resized_img
        #raise ValueError(f"Goodreads returned a bad url {resized_img}")


class NumPages(MappedSoupyField):
    @staticmethod
    def map(tag):
        return tag.text.strip().split()[0]


@dataclasses.dataclass
class BookFormerlyEntrustedToGoodreads:
    position: str
    cover: Cover
    cover_file: str = dataclasses.field(init=False)
    title: str
    author: str
    isbn: str
    isbn13: str
    asin: str
    num_pages: NumPages
    avg_rating: str
    num_ratings: str
    date_pub: str
    date_pub_edition: str
    rating: str

    # when anonymous, shelves is empty; makes sense
    #shelves: Shelves
    #notes: str
    review: str
    recommender: str
    comments: str
    votes: str
    read_count: int
    date_started: str
    date_read: str
    date_added: str
    date_purchased: str
    owned: str
    purchase_location: str
    condition: str
    format: str

    book_url: str = dataclasses.field(init=False) # the URI fragment
    book_id: str = dataclasses.field(init=False) # data-resource-id

    # def to_json(self):
    #     return json.dumps(self, cls=BookEncoder)

    def __post_init__(self):
        # book data is hidden in the `Cover` field
        log.debug(f"post-init for {self.title}")
        book_data = self.cover.source.find('div')
        self.book_id = book_data.attrs['data-resource-id']
        self.book_url = book_data.find('a').attrs['href']

        # clean any newlines that remain
        cleaned = []
        for field in dataclasses.fields(self):
            if '\n' in str(field):
                setattr(self, field.name, re.sub(r'\n[ ]+', ' ', str(field)))
                cleaned.append(field.name)

        if len(cleaned):
            log.info(f"cleaned {cleaned.join(',')}")

        print()

    @classmethod
    def from_book_list_page_list_item(cls, tag):
        """Extract a Book from the html fragment in the Book List (/review/list) page,"""
        instance_args = dict()
        valid_fields = { obj.name : obj for obj in dataclasses.fields(cls)}

        # grab all `tr.field` tags
        for book_field in tag.find_all('td', {'class': re.compile('.*field.*')}):
            # the field name is added into the `class` element property, so filter out some trash to find that
            try:
                field_name = [x for x in
                              filter(lambda fname: fname not in (
                                  'bookalike', 'field'), book_field.get('class')
                                     )
                              ][0]
            except IndexError:
                continue

            try:
                field_obj = valid_fields[field_name]
            except KeyError:
                continue

            # all field data is contained in a wrapper div, get rid of it
            book_raw = book_field.find('div', {'class': 'value'})  # .decode_contents().strip()
            log.debug(f"\t{field_name}: {book_raw}\n")

            # note: to get innerhtml for a bs4 tag, use .decode_contents().strip()

            if issubclass(field_obj.type, SoupyField):
                instance_args[field_name] = field_obj.type(book_raw)
            else:
                instance_args[field_name] = book_raw.text.strip()

        log.debug(f"successfully processed {instance_args.get('title')}")
        return BookFormerlyEntrustedToGoodreads(**instance_args)


class BookEncoder(json.JSONEncoder):
    def default(self, obj):
        data = {}
        if isinstance(obj, BookFormerlyEntrustedToGoodreads):
            for f in dataclasses.fields(obj):
                if isinstance(f, dataclasses.Field):
                    try:
                        data[f.name] = getattr(obj, f.name)
                    except Exception as ex:
                        log.error(f"could not serialize {obj} to json")
                else:
                    raise Exception
        elif isinstance(obj, SoupyField):
            return obj.value

        return data


class OwnedCollection(object):
    """Given a username and a download of owned books from GR,
    Read in all book metadata (including covers and other customizations)
    into an object.
    """
    username: str
    first_page: str
    books: Mapping[str, BookFormerlyEntrustedToGoodreads]
    owned: Mapping[str, Mapping]
    limit: int

    def __init__(self, username: str, owned: List, limit: int = None):
        self.username = username
        baseurl = os.path.join(goodreads_user_url, self.username)
        self.first_page = f"{baseurl}?print=true&shelf=ALL&page=1"
        self.books = {}
        self.index = 0
        self.owned = {o["book"]: o for o in owned}
        self.limit = limit

    def load_books_from_list_page(self, pageurl: str):
        """Grab a single book list page and extract Book objects.
        Recursively calls this method to exhaust paginator.
        """
        r = requests.get(pageurl)
        soup = BeautifulSoup(r.text, 'html.parser')
        book_trs = soup.find_all(
            'tr', {'class': 'bookalike review', 'id': re.compile('review_*')}
        )

        for tag in book_trs:

            book_obj = BookFormerlyEntrustedToGoodreads.from_book_list_page_list_item(tag)
            self.books[book_obj.title] = book_obj
            self.index += 1
            if self.limit and self.index >= self.limit:
                return

        try:
            next_page = soup.find('a', rel="next").get("href")
        except AttributeError:
            return
        else:
        #self.books.extend(
            self.load_books_from_list_page(f"{goodreads}{next_page}")
        #)


    def populate(self):
        """
        :param username:
        :return:
        """
        # populate the books list
        self.load_books_from_list_page(self.first_page)

        # match the books list against owned records
        for title, book in self.books.items():
            #title = str(book.title)

            try:
                ref = self.owned[title]
            except KeyError:
                log.debug(f"{title} not found in owned books")
                continue
            else:
                log.debug(f"you own {title} and its status is '{book.owned}'")

    def dump(self, pth, outfile='books.json', pretty=True):
        if not os.path.exists(pth):
            os.mkdir(pth)

        for title, book in self.books.items():
            img_file = os.path.basename(urlparse(str(book.cover)).path)
            resp = requests.get(book.cover, allow_redirects=True)
            resp.raise_for_status()
            open(os.path.join(pth, img_file), 'wb').write(resp.content)
            book.cover_file = img_file

        data = json.dumps(self.books, cls=BookEncoder, indent=2 if pretty else None)
        open(os.path.join(pth, outfile), 'w').write(data)



# Press the green button in the gutter to run the script.
if __name__ == '__main__':

    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument(
        '--books-path', dest='books_path', help="goodreads book export csv", default='./goodreads_library_export.csv'
    )
    parser.add_argument(
        '--owned-path', dest='owned_path', help="goodreads owned_books export json", default='./owned_book.json'
    )
    parser.add_argument('--username', dest="username")

    args = parser.parse_args()

    # l = Link()
    # l.x = 1
    # print(dir(l))

    # books = {}
    # with open(args.books_path, 'r') as fp:
    #     books_csv = csv.DictReader(fp)
    #     for record in books_csv:
    #         books[record['Title']] = copy(record)
    #
    with open(args.owned_path, 'r') as fp:
        owned = json.load(fp)
        del owned[0] # a header. thanks for the great well-formed JSON!

    recorded_books = OwnedCollection(args.username, owned) #, limit=50)
    recorded_books.populate()
    recorded_books.dump('./test')

    # owned_books = filter_owned_books(books, owned)
    #
    # for book in owned_books:
    #     book['Image'] = get_cover_image(book['Book Id'])
    #     print(book)



# See PyCharm help at https://www.jetbrains.com/help/pycharm/
