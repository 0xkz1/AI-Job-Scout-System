"""Exercise local listings through discovery, eligibility and document access."""
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pytest
import selection
import matcher
import run
import filter as job_filter
from local_jobs import local_job_role
from scraper_indeed import filter_jobs_by_keywords

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def config():return selection.load_config()

def posting(title,location='Edinburgh'):
    return {'title':title,'company':'Audit Fixture','location':location,
            'url':'https://example.invalid/local-audit','scraped_at':datetime.now().isoformat(),
            'description':'Receive deliveries and support the team. '*15,
            'analysis':{'experience_level':'entry_level','employment_types':['part_time'],
                        'salary':{'max':13.28,'period':'hourly'},'skills':['Manual Handling']},
            'match':{'composite_score':0.75}}

def app_function(name,namespace):
    tree=ast.parse((ROOT/'app.py').read_text())
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(ROOT/'app.py'),'exec'),namespace)
    return namespace[name]

@pytest.mark.parametrize('title',['Tesco Festive Colleague - Nights - Edinburgh Leith',
                                  'Warehouse Operatives','Kitchen Porters'])
def test_actual_title_variants_survive_discovery_and_salary_gate(title,config):
    item=posting(title)
    assert filter_jobs_by_keywords([item],config['keywords'])==[item]
    assert local_job_role(title,config) is not None
    assert job_filter.passes_filter(item,config)==(True,'')
    assert matcher.calculate_title_relevance(title,config=config)==1.0

@pytest.mark.parametrize('location',['London','Glasgow','Manchester','Tokyo, Japan','Remote'])
def test_other_cities_do_not_enter_local_ranked_pool(location,config):
    item=posting('Warehouse Operative',location)
    assert not job_filter.passes_filter(item,config)[0]
    assert selection.ranked_jobs(config,jobs=[item])==[]

@pytest.mark.parametrize('location',['Edinburgh','Leith','Newbridge, Edinburgh','EH11 4XX'])
def test_researched_locations_remain_eligible(location,config):
    assert job_filter.passes_filter(posting('Warehouse Operative',location),config)==(True,'')

def test_shared_cv_appears_in_standard_report_column(config,tmp_path):
    item=posting('Warehouse Operative')
    item['match']=matcher.analyze_match(item,config,skip_summary=True,skip_llm_context=True)
    run.generate_outputs([item],config,str(tmp_path))
    report=next((tmp_path/'00_matches').glob('*.md')).read_text()
    assert '\ncv: "[[career/cv/CV_Stock-Replenishment]]"' in report

def test_pdf_rows_recognise_shared_cv(config,tmp_path):
    namespace={'Path':Path,'datetime':datetime,'CV_DIR':tmp_path/'cvs',
               'CL_DIR':tmp_path/'letters','resolve_doc_base':lambda *a:'fixture'}
    rows=app_function('ranked_job_rows',namespace)([posting('Warehouse Operative')])
    assert rows[0]['has_cv'] and rows[0]['has_docs']
    assert rows[0]['local_job_role']=='warehouse_manual'

def test_adzuna_local_queries_are_uk_only_and_located(config,monkeypatch):
    import scraper_adzuna as api
    calls=[]
    def search(keyword,country,*args,**kwargs):
        calls.append((keyword,country,kwargs));return []
    monkeypatch.setattr(api,'scrape_adzuna_api',search)
    monkeypatch.setattr(api.time,'sleep',lambda *a:None)
    cfg=dict(config,keywords=['Warehouse Operative','Web Developer'],adzuna_countries=['gb','us'])
    api._scrape_adzuna_api_all(cfg,'dummy','dummy')
    local=[x for x in calls if x[0]=='Warehouse Operative']
    assert len(local)==1 and local[0][1]=='gb'
    assert local[0][2]['location']=='Edinburgh'
    assert len([x for x in calls if x[0]=='Web Developer'])==2


def test_professional_only_keyword_search_does_not_admit_local_aliases():
    assert filter_jobs_by_keywords([posting('Festive Colleague')],['Web Developer'])==[]


def test_adzuna_request_includes_where(monkeypatch):
    import scraper_adzuna as api
    seen=[]
    def get(url,params,timeout):
        seen.append(params);return SimpleNamespace(status_code=200,json=lambda:{'results':[]})
    monkeypatch.setattr(api.requests,'get',get)
    api.scrape_adzuna_api('Warehouse Operative','gb','dummy','dummy',max_pages=1,location='Edinburgh')
    assert seen[0]['where']=='Edinburgh'


def test_shared_cv_download_uses_the_authored_pdf(config):
    from local_jobs import local_job_cv_file
    source=local_job_cv_file('warehouse_manual',config)
    pdf=source.parent/'pdf'/source.stem/'Kazuki Yunome CV.pdf'
    downloads=[]
    ui=SimpleNamespace(download_button=lambda *args,**kwargs:downloads.append(kwargs),
                       caption=lambda *args:pytest.fail('Expected an available authored PDF'))
    controls=app_function('shared_cv_controls',{'st':ui})
    controls('warehouse_manual','test_download')
    assert len(downloads)==1 and downloads[0]['data']==pdf.read_bytes()
    assert downloads[0]['mime']=='application/pdf'


def test_stale_shared_pdf_is_not_offered_as_current(config,tmp_path,monkeypatch):
    import os,local_jobs
    source=tmp_path/'CV_Fixture.md';source.write_text('Updated verified CV')
    pdf=tmp_path/'pdf'/source.stem/'Kazuki Yunome CV.pdf'
    pdf.parent.mkdir(parents=True);pdf.write_bytes(b'older PDF')
    os.utime(pdf,(1,1))
    monkeypatch.setattr(local_jobs,'local_job_cv_file',lambda *args:source)
    notices=[]
    ui=SimpleNamespace(download_button=lambda *args,**kwargs:pytest.fail('Stale PDF was offered'),
                       caption=lambda text:notices.append(text))
    app_function('shared_cv_controls',{'st':ui})('warehouse_manual','test_stale')
    assert notices


def test_a_missing_shared_cv_does_not_create_a_dead_report_link(config,tmp_path,monkeypatch):
    import local_jobs
    monkeypatch.setattr(local_jobs,'local_job_cv_file',lambda *args:None)
    item=posting('Warehouse Operative')
    item['match']=matcher.analyze_match(item,config,skip_summary=True,skip_llm_context=True)
    run.generate_outputs([item],config,str(tmp_path))
    report=next((tmp_path/'00_matches').glob('*.md')).read_text()
    assert '\ncv:' not in report
    assert '\nshared_cv:' not in report


def test_dashboard_title_scoring_reuses_one_config(monkeypatch):
    import json
    calls=[]
    config=selection.load_config()
    def load():calls.append(True);return config
    monkeypatch.setattr(selection,'load_config',load)
    seen=[]
    def score(title,**kwargs):seen.append(kwargs['config']);return 1.0
    namespace={'json':json,'calculate_title_relevance':score}
    app_function('get_base_scores',namespace)(json.dumps([posting('Warehouse Operative'),posting('Kitchen Porter')]))
    assert len(calls)==1 and all(c is config for c in seen)
