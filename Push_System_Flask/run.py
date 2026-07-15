#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask 应用入口"""
import os
import sys

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()

if __name__ == '__main__':
    config = app.config
    app.run(
        host=config['HOST'],
        port=config['PORT'],
        debug=config['DEBUG']
    )
