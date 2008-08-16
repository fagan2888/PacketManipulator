#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2008 Adriano Monteiro Marques
#
# Author: Francesco Piccinno <stack.box@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA

import os
import os.path

import gtk
import gobject

from PM.Core.Const import PIXMAPS_DIR

icons = (
    'operation',
    'protocol',
    'locked',
    'packet',
    'layer',
    'sniff',

    'info',
    'warning',
    'error',

    'python',
    'terminal',
    'stock-close'
)

def register_icons():
    factory = gtk.IconFactory()
    pix_dir = PIXMAPS_DIR

    for icon_name in icons:
        for type, size in (('small', 16), ('normal', 32)):
            key = "%s_%s" % (icon_name, type)

            try:
                pixbuf = gtk.gdk.pixbuf_new_from_file(
                    os.path.join(pix_dir, "%s-%d.png" % (icon_name, size))
                )
                factory.add(key, gtk.IconSet(pixbuf))

            except gobject.GError:
                continue

    factory.add_default()

def get_pixbuf(stock_id):
    name, size = stock_id.split("_")

    if size == "small":
        size = 16
    elif size == "normal":
        size = 32
    else:
        raise Exception("Could not determine the pixel size")

    return gtk.gdk.pixbuf_new_from_file(os.path.join(PIXMAPS_DIR, "%s-%d.png" % (name, size)))