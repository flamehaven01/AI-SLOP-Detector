"""Test file for hallucinated dependencies detection."""

# ML imports that are never used
import torch
import tensorflow as tf
from transformers import AutoModel
import numpy as np
import pandas as pd

# HTTP imports that are never used
import requests
import aiohttp

# Database imports that are never used
import sqlalchemy
from pymongo import MongoClient

# Actually used import
import json


def process_data():
    """Process some data."""
    data = {"name": "test", "value": 42}
    result = json.dumps(data)
    return result


def main():
    """Main function."""
    print(process_data())
