"""Build B01-only metadata request, or validate a saved LLM response locally."""
import argparse
import json
from pathlib import Path

from datamate.ingestion.schema_advisor import build_request, validate_response, export_pending_review


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--document',type=Path,action='append',required=True)
    p.add_argument('--table',action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--response',type=Path)
    p.add_argument('--pending-relationships',type=Path)
    a=p.parse_args()
    if a.output.resolve().is_relative_to(a.bundle.resolve()) or any(a.output.resolve()==d.resolve() for d in a.document):
        p.error('output must be outside the baseline bundle and source documents')
    request=build_request(a.bundle,a.document,a.table)
    if a.pending_relationships and not a.response:p.error('--pending-relationships requires --response')
    result=request
    if a.response:
        raw=json.loads(a.response.read_text())
        if raw.get('request')!=request:raise ValueError('saved LLM response belongs to another request')
        result=validate_response(a.bundle,request,raw['response'])
        result['model_run']=raw.get('manifest',{})
        if a.pending_relationships:
            result['review_export']=export_pending_review(a.bundle,request,result,a.pending_relationships)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(a.output)

if __name__=='__main__':main()
