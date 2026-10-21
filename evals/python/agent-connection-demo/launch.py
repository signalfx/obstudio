import argparse

from dotenv import load_dotenv

parser = argparse.ArgumentParser()
parser.add_argument("--profile", required=True)
args = parser.parse_args()
load_dotenv(args.profile)

from app import main

main()
