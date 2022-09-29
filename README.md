# Goodreads extract owned book metadata

Requirements:
1. Data dump
2. Book export
3. Grab amazon books list and upload to {goodreads, system of choiuce)

Problems:
Owned book JSON export does not conain any metadata to join to books collection

# Notes
The Goodreads data dump, which contains (among other things)
    the set of owned books with custom covers, condition, and purchase date.
    However, the "owned books" data does not contain a Book ID, and so we need
    to match titles to extract a BookId from an owned book in order to access
    those covers and condition data.

    ref: https://help.goodreads.com/s/article/Why-are-you-removing-details-about-owned-books