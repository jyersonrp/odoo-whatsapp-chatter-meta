# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import os
import sys

# Auto-detect standard wkhtmltopdf install location on Windows
if sys.platform.startswith('win'):
    for standard_path in [
        r'C:\Program Files\wkhtmltopdf\bin',
        r'C:\Program Files (x86)\wkhtmltopdf\bin',
    ]:
        if os.path.isdir(standard_path) and standard_path not in os.environ.get('PATH', ''):
            os.environ['PATH'] = standard_path + os.pathsep + os.environ.get('PATH', '')

from . import models
from . import wizard
from . import controllers

