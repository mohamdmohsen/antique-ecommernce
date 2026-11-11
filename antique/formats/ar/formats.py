# Django's built-in Arabic number format writes 1200.50 as "1200,50". Money must read
# the same in both languages (the website already guarantees this with its own
# `money` filter), so the admin uses the same separators in Arabic as in English.
DECIMAL_SEPARATOR = "."
THOUSAND_SEPARATOR = ","
