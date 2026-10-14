"""Local income work survives career filters without admitting unrelated jobs."""
from pathlib import Path
import copy
import pytest
import yaml
import filter as job_filter
import matcher
import selection
from local_jobs import local_job_role

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def config():
    return yaml.safe_load((ROOT / 'config.yaml').read_text())

@pytest.mark.parametrize('title,role',[
 ('Administrator Part Time','business_administration'),
 ('Business Support Administrator','business_administration'),
 ('Operations Assistant','business_administration'),
 ('Warehouse Operative - Days - Part Time','warehouse_manual'),
 ('Parcelforce Warehouse Sorter','warehouse_manual'),
 ('Removals Porter','warehouse_manual'),
 ('Stock Assistant','warehouse_manual'),
 ('Kitchen Porter at Royal Botanic Garden Edinburgh','kitchen_porter'),
])
def test_local_titles_have_relevance(title,role,config):
    assert local_job_role(title, config) == role
    assert matcher.calculate_title_relevance(title, config=config) == 1.0

@pytest.mark.parametrize('title',[
 'Systems Administrator','IT Support Administrator','Linux Administrator',
 'ServiceNow Platform Administrator','Cloud Network Administrator',
 'UX Designer','Customer Support Engineer','Senior Software Engineer',
 'Support Worker','Porter', 'Warehouse Operativeship',
])
def test_technical_and_unrequested_titles_are_not_local(title,config):
    assert local_job_role(title,config) is None


def job(title,amount=12.71,period='hourly'):
    return {'title':title,'company':'Local Test Company','location':'Edinburgh',
            'url':'https://example.invalid/jobs/local',
            'description':('Receive and organise deliveries, check items carefully and work with colleagues. '
                           'Follow the supervisor instructions, keep work areas clean and follow safety procedures. ')*4,
            'analysis':{'salary':{'min':amount,'max':amount,'period':period},
                        'employment_types':['part_time'],'experience_level':'entry_level',
                        'skills':['Manual Handling'],'work_style':'onsite'}}

@pytest.mark.parametrize('title',['Warehouse Operative','Kitchen Porter','Administrator Part Time'])
def test_hourly_and_part_time_income_is_not_rejected_as_low_career_salary(title,config):
    assert job_filter.passes_filter(job(title),config) == (True,'')
    assert job_filter.passes_filter(job(title,18000,'annual'),config) == (True,'')

@pytest.mark.parametrize('title',['Junior Web Developer','Systems Administrator','IT Support Administrator'])
def test_professional_salary_floor_stays_active(title,config):
    ok,reason=job_filter.passes_filter(job(title),config)
    assert not ok and 'min £26000' in reason

@pytest.mark.parametrize('title',['Senior Warehouse Operative','Warehouse Driver','Nurse Administrator'])
def test_local_profiles_do_not_bypass_seniority_or_driving_or_clinical_exclusions(title,config):
    assert not job_filter.passes_filter(job(title),config)[0]
    if title != 'Senior Warehouse Operative':
        assert matcher.calculate_title_relevance(title,config=config) == 0.0


def test_description_mentions_do_not_unlock_an_unrequested_role(config):
    item=job('Junior Web Developer');item['description'] += ' Support the warehouse operative and kitchen porter.'
    assert not job_filter.passes_filter(item,config)[0]
    assert local_job_role(item['title'],config) is None


def test_disabling_profiles_restores_old_warehouse_gate(config):
    cfg=dict(config,local_job_profiles={})
    assert matcher.calculate_title_relevance('Warehouse Operative',config=cfg) == 0.0
    assert not job_filter.passes_filter(job('Warehouse Operative'),cfg)[0]


def test_search_budget_and_local_location_scope(config):
    pairs=selection.search_pairs(config)
    assert len(pairs)==44
    assert len(pairs)==len(set(pairs))
    local=[(kw,loc) for kw,loc in pairs if local_job_role(kw,config)]
    assert len(local)==8 and all(loc=='Edinburgh' for kw,loc in local)
    linkedin=selection.search_pairs(config,site='linkedin')
    assert all(loc=='Edinburgh' for kw,loc in linkedin if local_job_role(kw,config))
    assert ('Creative Technologist','Remote (Japan)') in linkedin
    assert len(linkedin)==54


def test_high_scoring_local_job_links_shared_cv_without_generating_technical_documents(config,tmp_path,monkeypatch):
    import run
    item=job('Warehouse Operative - Days - Part Time')
    item['match']=matcher.analyze_match(item,config,skip_summary=True,skip_llm_context=True)
    assert item['match']['title_relevance']==1.0
    item['match']['composite_score']=0.95
    def forbidden(*args,**kwargs):
        raise AssertionError('Local work must use the shared CV, not generate technical documents')
    monkeypatch.setattr(run,'generate_cv',forbidden)
    monkeypatch.setattr(run,'save_cover_letter',forbidden)
    run.generate_outputs([item],config,str(tmp_path))
    reports=list((tmp_path/'00_matches').glob('*.md'))
    assert len(reports)==1
    text=reports[0].read_text()
    assert 'local_job_role: "warehouse_manual"' in text
    assert 'shared_cv: "[[career/cv/CV_Stock-Replenishment]]"' in text
    assert not list((tmp_path/'10_cvs').glob('*.md'))
    assert not list((tmp_path/'10_cover-letters').glob('*.md'))
    # A nightly regeneration must preserve human-owned application/expiry flags.
    reports[0].write_text(text.replace('applied: false','applied: true').replace('expired: false','expired: true'))
    run.generate_outputs([item],config,str(tmp_path))
    assert 'applied: true' in reports[0].read_text()
    assert 'expired: true' in reports[0].read_text()


def test_local_context_sees_confirmed_practical_experience(config,monkeypatch):
    seen=[]
    monkeypatch.setattr(matcher,'_load_persona_summary',lambda:'Professional profile')
    def score(description,persona):
        seen.append(persona)
        return {'score':0.7,'reasoning':'Relevant prior removals and kitchen work.'}
    monkeypatch.setattr(matcher,'_ollama_context_score',score)
    result=matcher.analyze_match(job('Warehouse Operative'),config,skip_summary=True)
    assert result['local_job_role']=='warehouse_manual'
    assert len(seen)==1
    assert 'Hikkoshi-sha' in seen[0] and '2015–2017' in seen[0]
    assert 'Irohani-hoheto' in seen[0] and '2013–2015' in seen[0]


def test_income_titles_do_not_reset_professional_document_selection(config,tmp_path,monkeypatch):
    import run
    captured=[]
    original=selection.select_top
    def selected(stage,cfg,jobs):
        captured.append([j['title'] for j in jobs])
        return original(stage,cfg,jobs=jobs)
    monkeypatch.setattr(selection,'select_top',selected)
    local=job('Warehouse Operative')
    local['match']=matcher.analyze_match(local,config,skip_summary=True,skip_llm_context=True)
    run.generate_outputs([local],config,str(tmp_path))
    assert captured[0]==[]


def test_local_jobs_remain_ranked_but_do_not_consume_document_or_review_slots(config):
    items=[job('Warehouse Operative'),job('Junior Web Developer',35000,'annual')]
    for item,score in zip(items,[0.99,0.7]):
        item['url'] += item['title'].replace(' ','-')
        item['match']=matcher.analyze_match(item,config,skip_summary=True,skip_llm_context=True)
        item['match']['composite_score']=score
    assert len(selection.ranked_jobs(config,jobs=items))==2
    for stage in ['generation','review']:
        picked=selection.select_top(stage,config,jobs=items,percent=100)
        assert [j['title'] for j in picked]==['Junior Web Developer']


def test_shipped_configuration_fits_measured_scraper_timeouts(config):
    from invariants import check_scrape_fits_its_timeout
    assert check_scrape_fits_its_timeout(config)==[]


@pytest.mark.parametrize('mode', ['--dry-run', '--generate-only', '--review-only'])
def test_bridge_does_not_generate_or_queue_local_jobs(config,tmp_path,monkeypatch,capsys,mode):
    import sys
    import jis_hermes_bridge as bridge
    data=tmp_path/'_analyzed.json'
    data.write_text('[]')
    item=job('Warehouse Operative')
    item['match']={'composite_score':0.99}
    monkeypatch.setattr(bridge,'ANALYZED_FILE',data)
    monkeypatch.setattr(selection,'load_config',lambda:config)
    monkeypatch.setattr(selection,'ranked_jobs',lambda **kwargs:[item])
    def forbidden(*args,**kwargs):
        raise AssertionError('Local jobs must not enter autonomous document review')
    monkeypatch.setattr(bridge,'generate_documents',forbidden)
    monkeypatch.setattr(bridge,'create_review_task',forbidden)
    monkeypatch.setattr(sys,'argv',['jis_hermes_bridge.py',mode])
    bridge.main()
    assert 'Found 0 jobs' in capsys.readouterr().out
