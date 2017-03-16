#!/usr/bin/env python3

import urllib
from collections import OrderedDict
from datetime import datetime
from db import DB
from flask import Flask
from flask import abort
from flask import render_template
from flask import request

app = Flask(__name__)

def break_punctuation(text):
    #provide additional line breaking opportunities
    return (text
        .replace('(', '<wbr/>(')
        .replace(')', ')<wbr/>')
        .replace(',', ',<wbr/>')
        .replace('.', '.<wbr/>')
        .replace(':', '<wbr/>:<wbr/>')
        .replace('-', '-<wbr/>')
    )

def int_arg(name, default = 0):
    arg = request.args.get(name)
    try:
        return int(arg) if arg else default
    except ValueError:
        abort(400)

def overview_to_breakdown(conflict_overview):
    breakdown = {}
    submitter1_significances = set()
    submitter2_significances = set()
    total = 0

    for row in conflict_overview:
        clin_sig1 = row['clin_sig1']
        clin_sig2 = row['clin_sig2']
        count = row['count']

        if not clin_sig1 in breakdown:
            breakdown[clin_sig1] = {}
        if not clin_sig2 in breakdown[clin_sig1]:
            breakdown[clin_sig1][clin_sig2] = 0
        breakdown[clin_sig1][clin_sig2] += count

        submitter1_significances.add(clin_sig1)
        submitter2_significances.add(clin_sig2)

        total += count

    #sort alphabetically to be consistent if there are two or more unranked significance terms
    submitter1_significances = sorted(submitter1_significances)
    submitter2_significances = sorted(submitter2_significances)

    #sort by rank
    submitter1_significances = sorted(submitter1_significances, key=significance_rank)
    submitter2_significances = sorted(submitter2_significances, key=significance_rank)

    return breakdown, submitter1_significances, submitter2_significances, total

def significance_rank(significance):
    significance_ranks = [
        'pathogenic',
        'likely pathogenic',
        'uncertain significance',
        'likely benign',
        'benign',
        'risk allele',
        'assocation',
        'protective allele',
        'drug response',
        'confers sensitivity',
        'other',
        'not provided',
    ]
    try:
        rank = significance_ranks.index(significance)
    except ValueError:
        rank = len(significance_ranks) - 2.5 #insert after everything but "other" and "not provided"
    return rank

@app.template_filter('date')
def prettify_date(iso_date):
    return datetime.strptime(iso_date[:10], '%Y-%m-%d').strftime('%d %b %Y') if iso_date else ''

@app.template_filter('orspace')
def string_or_space(path):
    return path if path else '\u200B'

@app.template_filter('querysuffix')
def query_suffix(request):
    return '?' + request.query_string.decode('utf-8') if request.query_string else ''

@app.template_filter('quotepath')
def quote_path(path):
    return urllib.parse.quote(path).replace('/', '%252F')

@app.template_filter('rcvlink')
def rcv_link(rcv):
    return '<a href="https://www.ncbi.nlm.nih.gov/clinvar/' + rcv + '/">' + rcv + '</a>'

@app.context_processor
def template_functions():
    def submitter_link(submitter_id, submitter_name):
        if submitter_id == 0:
            return submitter_name
        return '<a href="https://www.ncbi.nlm.nih.gov/clinvar/submitters/' + str(submitter_id) + '/">' + break_punctuation(submitter_name) + '</a>'

    def variant_link(variant_id, variant_name):
        return '<a href="https://www.ncbi.nlm.nih.gov/clinvar/variation/' + str(variant_id) + '/">' + break_punctuation(variant_name) + '</a>'

    return {
        'submitter_link': submitter_link,
        'variant_link': variant_link,
    }

@app.route('/conflicting-variants-by-significance')
@app.route('/conflicting-variants-by-significance/<significance1>/<significance2>')
def conflicting_variants_by_significance(significance1 = None, significance2 = None):
    db = DB()

    if not significance2:
        conflict_overview = db.conflict_overview(
            min_stars=int_arg('min_stars'),
            method=request.args.get('method'),
            corrected_terms=request.args.get('corrected_terms'),
        )

        breakdown, submitter1_significances, submitter2_significances, total = overview_to_breakdown(conflict_overview)

        return render_template(
            'conflicting-variants-by-significance.html',
            breakdown=breakdown,
            submitter1_significances=submitter1_significances,
            submitter2_significances=submitter2_significances,
            total=total,
            method_options=db.methods(),
        )

    significance1 = significance1.replace('%2F', '/')
    significance2 = significance2.replace('%2F', '/')

    variants = db.variants(
        significance1=significance1,
        significance2=significance2,
        min_stars=int_arg('min_stars'),
        method=request.args.get('method'),
        corrected_terms=request.args.get('corrected_terms'),
    )

    return render_template(
        'conflicting-variants-by-significance-2significances.html',
        title='Variants reported as ' + significance1 + ' and ' + significance2,
        significance1=significance1,
        significance2=significance2,
        variants=variants,
        method_options=db.methods(),
    )

@app.route('/conflicting-variants-by-submitter')
@app.route('/conflicting-variants-by-submitter/<submitter1_id>')
@app.route('/conflicting-variants-by-submitter/<submitter1_id>/<submitter2_id>')
@app.route('/conflicting-variants-by-submitter/<submitter1_id>/<submitter2_id>/<significance1>/<significance2>')
def conflicting_variants_by_submitter(submitter1_id = None, submitter2_id = None, significance1 = None, significance2 = None):
    db = DB()

    if submitter1_id == None:
        return render_template(
            'conflicting-variants-by-submitter-index.html',
            total_conflicting_variants_by_submitter=db.total_variants_by_submitter(min_conflict_level=1),
        )

    try:
        submitter1_id = int(submitter1_id)
    except ValueError:
        return abort(404)

    submitter1_info = db.submitter_info(submitter1_id)
    if not submitter1_info:
        submitter1_info = {'id': submitter1_id, 'name': str(submitter1_id)}

    if submitter2_id == None:
        conflict_overview = db.conflict_overview(
            submitter1_id=submitter1_id,
            min_stars=int_arg('min_stars'),
            method=request.args.get('method'),
            corrected_terms=request.args.get('corrected_terms'),
        )
        submitter_primary_method = db.submitter_primary_method(submitter1_id)

        summary = OrderedDict()
        for row in conflict_overview:
            submitter2_id = row['submitter2_id']
            submitter2_name = row['submitter2_name']
            conflict_level = row['conflict_level']
            count = row['count']
            if not submitter2_id in summary:
                summary[submitter2_id] = {
                    'name': submitter2_name,
                    1: 0,
                    2: 0,
                    3: 0,
                    4: 0,
                    5: 0,
                    'total': 0,
                }
            summary[submitter2_id][conflict_level] += count
            summary[submitter2_id]['total'] += count

        breakdown, submitter1_significances, submitter2_significances, total = overview_to_breakdown(conflict_overview)

        return render_template(
            'conflicting-variants-by-submitter-1submitter.html',
            submitter1_info=submitter1_info,
            submitter2_info={'id': 0, 'name': 'All other submitters'},
            submitter_primary_method=submitter_primary_method,
            summary=summary,
            breakdown=breakdown,
            submitter1_significances=submitter1_significances,
            submitter2_significances=submitter2_significances,
            total=total,
            method_options=db.methods(),
        )

    try:
        submitter2_id = int(submitter2_id)
    except ValueError:
        abort(404)

    submitter2_info = db.submitter_info(submitter2_id)
    if not submitter2_info:
        if submitter2_id == 0:
            submitter2_info = {'id': 0, 'name': 'any other submitter'}
        else:
            submitter2_info = {'id': submitter2_id, 'name': str(submitter2_id)}

    if not significance1:
        conflict_overview = db.conflict_overview(
            submitter1_id=submitter1_id,
            submitter2_id=submitter2_id,
            min_stars=int_arg('min_stars'),
            method=request.args.get('method'),
            corrected_terms=request.args.get('corrected_terms'),
        )

        breakdown, submitter1_significances, submitter2_significances, total = overview_to_breakdown(conflict_overview)

        return render_template(
            'conflicting-variants-by-submitter-2submitters.html',
            submitter1_info=submitter1_info,
            submitter2_info=submitter2_info,
            breakdown=breakdown,
            submitter1_significances=submitter1_significances,
            submitter2_significances=submitter2_significances,
            total=total,
            method_options=db.methods(),
        )

    significance1 = significance1.replace('%2F', '/')
    significance2 = significance2.replace('%2F', '/')

    variants = db.variants(
        submitter1_id=submitter1_id,
        submitter2_id=submitter2_id,
        significance1=significance1,
        significance2=significance2,
        min_stars=int_arg('min_stars'),
        method=request.args.get('method'),
    )
    return render_template(
        'conflicting-variants-by-submitter-2significances.html',
        submitter1_info=submitter1_info,
        submitter2_info=submitter2_info,
        significance1=significance1,
        significance2=significance2,
        variants=variants,
        method_options=db.methods(),
    )

@app.route('/')
def index():
    db = DB()
    return render_template(
        'index.html',
        max_date=db.max_date(),
    )

@app.route('/significance-terms')
@app.route('/significance-terms/', defaults={'term': ''})
@app.route('/significance-terms/<term>')
def significance_terms(term = None):
    db = DB()

    if term == None:
        return render_template(
            'significance-terms-index.html',
            total_significance_terms_over_time=db.total_significance_terms_over_time(),
            significance_term_info=db.significance_term_info(),
            old_significance_term_info=db.old_significance_term_info(),
        )

    term = term.replace('%2F', '/')

    return render_template(
        'significance-terms.html',
        term=term,
        total_significance_terms=db.total_significance_terms(term),
    )

@app.route('/submissions-by-gene')
@app.route('/submissions-by-gene/<gene>')
def submissions_by_gene(gene = None, variant_id = None):
    db = DB()

    if not gene:
        total_submissions_by_gene=db.total_submissions_by_gene(
            min_stars=int_arg('min_stars'),
            method=request.args.get('method'),
            min_conflict_level=int_arg('min_conflict_level'),
        )
        return render_template(
            'submissions-by-gene-index.html',
            total_submissions_by_gene=total_submissions_by_gene,
            method_options=db.methods(),
        )

    gene = gene.replace('%2F', '/')
    total_submissions_by_variant=db.total_submissions_by_variant(
        gene,
        min_stars=int_arg('min_stars'),
        method=request.args.get('method'),
        min_conflict_level=int_arg('min_conflict_level'),
    )
    return render_template(
        'variants-by-gene.html',
        title='Variants in ' + gene,
        total_submissions_by_variant=total_submissions_by_variant,
        method_options=db.methods(),
    )

@app.route('/submissions-by-variant/<variant_id>')
def submissions_by_variant(variant_id):
    db = DB()

    submissions=db.submissions(
        variant_id=variant_id,
        min_stars=int_arg('min_stars'),
        method=request.args.get('method'),
        min_conflict_level=int_arg('min_conflict_level'),
    )
    variant_name=db.variant_name(variant_id)
    return render_template(
        'submissions-by-variant.html',
        variant_name=variant_name,
        variant_id=variant_id,
        submissions=submissions,
        method_options=db.methods(),
    )

@app.route('/total-conflicting-submissions-by-method')
def total_conflicting_submissions_by_method():
    db = DB()
    return render_template(
        'total-conflicting-submissions-by-method.html',
        total_conflicting_submissions_by_method_over_time=db.total_conflicting_submissions_by_method_over_time(),
        max_date=db.max_date(),
    )

@app.route('/total-submissions-by-method')
def total_submissions_by_method():
    db = DB()
    return render_template(
        'total-submissions-by-method.html',
        total_submissions_by_method_over_time=db.total_submissions_by_method_over_time(),
        max_date=db.max_date(),
    )

@app.route('/total-submissions-by-country')
@app.route('/total-submissions-by-country/', defaults={'country': ''})
@app.route('/total-submissions-by-country/<country>')
def total_submissions_by_country(country = None):
    db = DB()

    if country == None:
        return render_template(
            'total-submissions-by-country-index.html',
            total_submissions_by_country=db.total_submissions_by_country(),
        )

    country = country.replace('%2F', '/')

    return render_template(
        'total-submissions-by-country.html',
        country=country,
        total_submissions_by_submitter=db.total_submissions_by_submitter(country=country),
    )
