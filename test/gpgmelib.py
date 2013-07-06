# -*- encoding: utf-8 -*-
#
# Copyright (c) 2011 Ralf Schlatterbeck, rsc@runtux.com.
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

import shutil, os
try:
    import pyme, pyme.core
except ImportError:
    pyme = None

pgp_test_key = """
-----BEGIN PGP PRIVATE KEY BLOCK-----
Version: GnuPG v1.4.10 (GNU/Linux)

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
=3uFZ
-----END PGP PRIVATE KEY BLOCK-----
"""

john_doe_key = """
-----BEGIN PGP PRIVATE KEY BLOCK-----
Version: GnuPG v1.4.10 (GNU/Linux)

lQHYBE6NwvABBACxg7QqV2qHywwM3wae6HAHJVEo7EeYA6Lv0pZlW3Aw4CCCnpgJ
jA7CekGFcmGmoCaN9ezuVAPTgUlK4yt8a7P6cT0vw1q341Om9IEKAu59RpNZN/H9
6GfZ95bU51W/hdTFysH1DRwbCR3MowvLeA6Pk4cZlPsYHD0SD3De2i1BewARAQAB
AAP+IRi4L6jKwPS3k3LFrj0SHhL0Fdgv5QTQjTxLNCyfN02iYhglqqoFWncm3jWc
RU/YwGEYwrrBV97kBmVihzkhfgFRsxynE9PMGKKEAuRcAl21RPJDFA6Dlnp6M2No
rR6eoAhrlZ8+KsK9JaXSMalzO/Yh4u3mOinq3f3XL96wAEkCAMAxeZMF5pnXARNR
Y7u2clhNNnLuf+BzpENCFMaWzWPyTcvbf4xNK7ZHPxFVZpX5/qAPJ8rnTaOTHxnN
5PgqbO8CAOxyrTw/muakTJLg+FXdn8BgxZGJXMT7KmkU9SReefjo7c1WlnZxKIAy
6vLIG8WMGpdfCFDve0YLr/GGyDtOjDUB/RN3gn6qnAJThBnVk2wESZVx41fihbIF
ACCKc9heFskzwurtvvp+bunM3quwrSH1hWvxiWJlDmGSn8zQFypGChifgLQZSm9o
biBEb2UgPGpvaG5AdGVzdC50ZXN0Poi4BBMBAgAiBQJOjcLwAhsDBgsJCAcDAgYV
CAIJCgsEFgIDAQIeAQIXgAAKCRC/z7qg+FujnPWiA/9T5SOGraRNIVVIyvJvYwkG
OTAfQ0K3QMlLoQMPmaEbx9Q+isF15M9sOMcl1XGO4UNWuCPIIN8z/y/OLgAB0ZuL
GlnAPPOOZ+MlaUXiMYo8oi416QZrMDf2H/Nkc10csiXm+zMl8RqeIQBEeljNyJ+t
MG1EWn/PHTwFTd/VePuQdJ0B2AROjcLwAQQApw+72jKy0/wqg5SAtnVSkA1F3Jna
/OG+ufz5dX57jkMFRvFoksWIWqHmiCjdE5QV8j+XTnjElhLsmrgjl7aAFveb30R6
ImmcpKMN31vAp4RZlnyYbYUCY4IXFuz3n1CaUL+mRx5yNJykrZNfpWNf2pwozkZq
lcDI69ymIW5acXUAEQEAAQAD/R7Jdf98l1scngMYo228ikYUxBqm2eX/fiQNXDWM
ZR2u+TJ9O53MvFejfXX7Pd6lTDQUBwDFncjgXO0YYSrMzabhqpqoKLqOIpZmBuWC
Hh1lvcFoIYoDR2LkiJ9EPBUEVUBDsUO8ajkILEE3G+DDpCaf9Vo82lCVyhDESqyt
v4lxAgDOLpoq1Whv5Ejr6FifTWytCiQjH2P1SmePlQmy6oEJRUYA1t4zYrzCJUX8
VAvPjh9JXilP6mhDbyQArWllewV9AgDPbVOf75ktRwfhje26tZsukqWYJCc1XvoH
3PTzA7vH1HZZq7dvxa87PiSnkOLEsIAsI+4jpeMxpPlQRxUvHf1ZAf9rK3v3HMJ/
2xVzwK24Oaj+g2O7D/fdqtLFGe5S5JobnTyp9xArDAhaZ/AKfDMYjUIKMP+bdNAf
y8fQUtuawFltm1GInwQYAQIACQUCTo3C8AIbDAAKCRC/z7qg+FujnDzYA/9EU6Pv
Ci1+DCtxjnq7IOvOjqExhFNGvN9Dw17Tl8HcyW3if9v5RxeSWYKl0DhzVdzMQgH/
78q4F4W1q2IkB7SCpXizHLIc3eh8iZkbWZE+CGPvTpqyF03Yi16qhxpAbkGs2Yhq
jTx5oJ4CL5fybBOZLg+BTlK4HIee6xEcbNoq+A==
=ZKBW
-----END PGP PRIVATE KEY BLOCK-----
"""

ownertrust = """
723762CD5A5FECB76DC72DF85ADCFD5631C38741:6:
2940C247A1FBAD508A1AF24BBFCFBAA0F85BA39C:6:
"""

pgphome = 'pgp-test-home'
def setUpPGP():
    # prevent test from failing if left over from earlier run:
    if os.path.exists(pgphome):
        shutil.rmtree(pgphome)
    os.mkdir(pgphome)
    os.environ['GNUPGHOME'] = pgphome
    # gpgme_check_version() must have been called once in a programm
    # to initialise some subsystems of gpgme. See roundup/roundupdb.py.
    ctx = pyme.core.Context()
    key = pyme.core.Data(pgp_test_key)
    ctx.op_import(key)
    key = pyme.core.Data(john_doe_key)
    ctx.op_import(key)
    # trust-modelling with pyme isn't working in 0.8.1
    # based on libgpgme11 1.2.0, also tried in C -- same thing.
    otrust = os.popen ('gpg --import-ownertrust 2> /dev/null', 'w')
    otrust.write(ownertrust)
    otrust.close()

def tearDownPGP():
    if os.path.exists(pgphome):
        shutil.rmtree(pgphome)


# vim: set filetype=python sts=4 sw=4 et si :
