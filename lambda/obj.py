#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
"""A thin object wrapper around a dictionary.

An object to hold key-value data accessible both as properties of the object
and as if the object were a dictionary.  Can be constructed with keyword
parameters.  Essentially, a thin object wrapper around a dictionary.

"""

__license__ = "MIT"
'''
© Copyright 2012, Isaac Greenspan

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

class Obj (object):
    """A thin object wrapper around a dictionary.

    An object to hold key-value data accessible both as properties of the
    object and as if the object were a dictionary.  Can be constructed with
    keyword parameters.  Essentially, a thin object wrapper around a
    dictionary.

    """
    def __init__(self, **kwargs):
        self.__dict__ = kwargs
    def __repr__(self):
        return '<Obj %s>' % repr(self.__dict__)
    def __contains__(self, item):
        return item in self.__dict__
    def __getitem__(self, item):
        if item in self.__dict__:
            return self.__dict__[item]
        else:
            raise KeyError("'%s'" % item)
    def __setitem__(self, item, value):
        self.__dict__[item] = value
    def __delitem__(self, item):
        del self.__dict__[item]
    def __len__(self):
        return len(self.__dict__)
