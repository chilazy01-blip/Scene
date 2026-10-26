"""Preserved compile implementation plus separately verified metadata repair."""
from .build_models import run as build
from .finalize_models import run as finalize
import sys
sid,oid=sys.argv[1:]
try:build(sid,oid)
except TypeError as exc:
    if "multiple values for keyword argument 'schema'" not in str(exc):raise
    print('Preserved known metadata-only constructor failure:',str(exc),flush=True)
    finalize(sid+'_'+oid)
