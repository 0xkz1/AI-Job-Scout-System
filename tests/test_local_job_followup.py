"""Keep local-work routing intact across nightly and manual entry points."""
import ast,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
import matcher,selection,run
from local_jobs import local_persona_extra

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def config():return selection.load_config()

def item(title='Warehouse Operative'):
    return {'title':title,'company':'Followup Fixture','location':'Edinburgh',
            'url':'https://example.invalid/'+title.replace(' ','-'),
            'description':'Receive and organise deliveries and work with the team. '*15,
            'analysis':{'experience_level':'entry_level','employment_types':['part_time'],
                        'salary':{'max':13.28,'period':'hourly'},'skills':['Manual Handling']}}

def scored(config):
    job=item();job['match']=matcher.analyze_match(job,config,skip_summary=True,skip_llm_context=True)
    return job


def test_core_renderer_and_save_entrypoint_retain_local_cv_metadata(config,tmp_path):
    job=scored(config)
    direct=matcher.generate_match_report(job,job['match'],config=config)
    saved=Path(matcher.save_match_report(job,job['match'],str(tmp_path))).read_text()
    for text in [direct,saved]:
        assert text.count('local_job_role: "warehouse_manual"')==1
        assert '\ncv: "[[career/cv/CV_Stock-Replenishment]]"' in text
        assert '\nshared_cv: "[[career/cv/CV_Stock-Replenishment]]"' in text


def test_nightly_regeneration_keeps_local_fields(config,tmp_path,monkeypatch):
    import regen_match_reports as regen
    job=scored(config);folder=tmp_path/'matches';folder.mkdir()
    report=folder/(matcher.make_safe_name(job['company'],job['title'])+'.md')
    report.write_text(matcher.generate_match_report(job,job['match'],config=config))
    db=tmp_path/'jobs.json';db.write_text(json.dumps([job]))
    monkeypatch.setattr(regen,'DB_PATH',db);monkeypatch.setattr(regen,'MATCH_DIR',folder)
    monkeypatch.setattr(regen,'APPLY',True)
    regen.main()
    assert report.read_text().count('local_job_role: "warehouse_manual"')==1
    assert 'shared_cv:' in report.read_text()


def test_explicit_regeneration_limit_does_not_select_or_count_local_work(config,tmp_path,monkeypatch,capsys):
    import regen_top_docs as regen
    jobs=[dict(item(),match={'composite_score':0.99}),
          dict(item('Junior Web Developer'),match={'composite_score':0.80})]
    monkeypatch.setattr(regen,'ranked_jobs',lambda *a:jobs)
    monkeypatch.setattr(regen.gen_version if hasattr(regen,'gen_version') else __import__('gen_version'),'pair_lock_reason',lambda *a:None)
    monkeypatch.setattr(sys,'argv',['regen_top_docs.py','--limit','1','--dry-run'])
    assert regen.main()==0
    output=capsys.readouterr().out
    assert 'Junior_Web_Developer' in output and 'Warehouse_Operative' not in output


def test_explicit_review_limit_does_not_select_or_count_local_work(config,tmp_path,monkeypatch):
    import rereview_top as review
    jobs=[dict(item(),match={'composite_score':0.99}),
          dict(item('Junior Web Developer'),match={'composite_score':0.80})]
    docs=tmp_path/'cvs';docs.mkdir()
    for job in jobs:(docs/(matcher.make_safe_name(job['company'],job['title'])+'_CV.md')).write_text('CV fixture')
    verdict=tmp_path/'verdict.md';verdict.write_text('No findings.')
    calls=[]
    monkeypatch.setattr(selection,'ranked_jobs',lambda *a:jobs)
    monkeypatch.setattr(review,'CV_DIR',docs);monkeypatch.setattr(review.gen_version,'is_locked',lambda *a:False)
    monkeypatch.setattr(review,'run_review',lambda kind,path,job:(calls.append(job['title']) or verdict))
    monkeypatch.setattr(review,'_extract_score',lambda text:(80,False,0))
    monkeypatch.setattr(sys,'argv',['rereview_top.py','--limit','1','--kind','CV'])
    assert review.main()==0
    assert calls==['Junior Web Developer']


@pytest.mark.parametrize('module_name',['llm_context_backfill','rescore_context'])
def test_nightly_rescoring_receives_verified_local_cv(module_name,config,tmp_path,monkeypatch):
    import importlib
    module=importlib.import_module(module_name)
    job=scored(config);job['match'].pop('context_persona_chars',None)
    job['match']['context_source']='tfidf';job['match']['summary_en']='Existing summary'
    db=tmp_path/'jobs.json';db.write_text(json.dumps([job]))
    seen=[]
    def score(description,persona,**kwargs):seen.append(persona);return {'score':0.4}
    monkeypatch.setattr(matcher,'_load_persona_summary',lambda:'Professional profile')
    monkeypatch.setattr(matcher,'_ollama_context_score',score)
    monkeypatch.setattr(module.time,'sleep',lambda *a:None)
    if module_name=='llm_context_backfill':
        monkeypatch.setattr(module,'ANALYZED_PATH',db)
        monkeypatch.setattr(module,'_load_persona_summary',lambda:'Professional profile')
        monkeypatch.setattr(module,'_ollama_context_score',score)
    else:monkeypatch.setattr(module,'ANALYZED',db)
    monkeypatch.setattr(sys,'argv',[module_name+'.py','--limit','1'])
    module.main()
    assert len(seen)==1 and 'Hikkoshi-sha' in seen[0] and '2015–2017' in seen[0]
    if module_name=='rescore_context':
        result=json.loads(db.read_text())[0]
        assert result['match']['context_persona_chars']==len(seen[0])


def test_local_persona_stamp_does_not_create_an_endless_rescore(config):
    import rescore_context
    job=scored(config);base='Professional profile'
    rescore_context.apply(job,{'score':0.4},len(base+local_persona_extra(job,config)),config)
    assert rescore_context.due([job],config,persona_chars=len(base))==[]


def test_guardian_can_launch_without_a_display(monkeypatch):
    import scraper_guardian as guardian
    import asyncio
    seen=[]
    class StopAfterLaunch(Exception):pass
    async def launch(**kwargs):seen.append(kwargs);raise StopAfterLaunch
    monkeypatch.delenv('DISPLAY',raising=False)
    browser=SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    with pytest.raises(StopAfterLaunch):
        asyncio.run(guardian.scrape_guardian('Kitchen Porter','Edinburgh',max_pages=1,playwright_instance=browser))
    assert seen[0]['headless'] is True


def test_old_professional_stamp_cannot_hide_missing_local_cv(config):
    import rescore_context
    job=scored(config)
    job['match']['context_persona_chars']=50000
    assert rescore_context.due([job],config,persona_chars=50000)==[job]
