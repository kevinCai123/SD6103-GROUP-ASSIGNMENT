"""Independently recompute all six final query results from prepared CSVs.

This validation uses pandas, not PostgreSQL or the SQL statements under test.
Two-decimal outputs allow 0.011 tolerance for decimal/binary rounding differences.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def main():
    tables = {name: pd.read_csv(ROOT/'data/prepared'/f'{name}.csv',low_memory=False) for name in
              ['town','hdb_block','hdb_flat','source_file','resale_transaction',
               'hawker_centre','block_hawker_distance']} 
    
    sales = (tables['resale_transaction'].merge(tables['hdb_flat'],on='flat_id',validate='m:1')
             .merge(tables['hdb_block'],on='block_id',validate='m:1')
             .merge(tables['town'],on='town_id',validate='m:1')) 
    
    assert len(sales) == len(tables['resale_transaction']) 

    sales['price_per_sqm'] = sales.resale_price / sales.floor_area_sqm
    sales['sale_year'] = sales.transaction_month.str[:4].astype(int) 

    estimates = (99-(sales.sale_year-sales.lease_commence_year))*12 

    sales['effective_lease'] = sales.remaining_lease_months_reported.fillna(estimates.where(estimates.between(0,1188)))
    sales['lease_bucket'] = pd.cut(sales.effective_lease,[-1,599,839,1079,1188],
        labels=['0-<50 years','50-<70 years','70-<90 years','90-99 years']).astype(object).fillna('UNKNOWN') 
    
    sales['reported'] = sales.remaining_lease_months_reported.notna().astype(int)
    sales['estimated'] = ((sales.reported==0)&sales.effective_lease.notna()).astype(int) 

    def nearest(market=False): 

        centres = tables['hawker_centre']
        eligible = centres.centre_type.isin(['HC','MHC']) 

        if market:
            eligible &= centres.market_produce_stalls > 0
        distances = tables['block_hawker_distance'].merge(centres[eligible],on='hawker_id',validate='m:1')
        n = distances.sort_values(['block_id','distance_m','hawker_id']).drop_duplicates('block_id')
        n['proximity_class'] = np.select([n.distance_m<500,n.distance_m<1000],['NEAR','MEDIUM'],default='FAR')
        return n[['block_id','hawker_id','centre_name','distance_m','proximity_class']] 
    
    near = sales.merge(nearest(),on='block_id',validate='m:1')
    fresh = sales.merge(nearest(True),on='block_id',validate='m:1')
    expected = {} 

    q1 = sales[(sales.transaction_month>='1997-01-01')&(sales.transaction_month<'2000-01-01')&sales.flat_type.isin(['4 ROOM','5 ROOM'])]
    expected['Q1'] = q1.groupby(['town_name','flat_type']).agg(avg_price_per_sqm=('price_per_sqm','mean'),transaction_volume=('transaction_id','size')).reset_index() 
    expected['Q2'] = sales.groupby(['town_name','lease_bucket']).agg(
        median_resale_price=('resale_price','median'),avg_price_per_sqm=('price_per_sqm','mean'),
        transaction_volume=('transaction_id','size'),reported_lease_count=('reported','sum'),estimated_lease_count=('estimated','sum')).reset_index() 
    
    three = sales[sales.flat_type=='3 ROOM']
    largest = three.groupby('town_name').floor_area_sqm.mean().reset_index(name='avg_floor_area_sqm').sort_values(['avg_floor_area_sqm','town_name'],ascending=[False,True]).head(10)
    expected['Q3'] = three.merge(largest,on='town_name').groupby(['town_name','avg_floor_area_sqm','sale_year']).agg(highest_resale_price=('resale_price','max'),transaction_volume=('transaction_id','size')).reset_index()
    averages = near.pivot_table(index=['town_name','flat_type'],columns='proximity_class',values='resale_price',aggfunc='mean')

    q4 = averages.reindex(columns=['NEAR','FAR']).rename(columns={'NEAR':'avg_price_near_hawker','FAR':'avg_price_far_hawker'})
    q4['price_diff_percentage'] = 100*(q4.avg_price_near_hawker-q4.avg_price_far_hawker)/q4.avg_price_far_hawker
    expected['Q4'] = q4.reset_index().rename(columns={'town_name':'town'}) 

    q5 = fresh.groupby(['town_name','proximity_class']).agg(avg_resale_price=('resale_price','mean'),transaction_volume=('transaction_id','size')).reset_index()
    expected['Q5'] = q5[q5.avg_resale_price>250000] 

    q6 = near.merge(tables['source_file'],on='source_file_id',validate='m:1').groupby(['town_name','centre_name','date_basis']).agg(transaction_volume=('transaction_id','size'),avg_price_per_sqm=('price_per_sqm','mean'),avg_distance_m=('distance_m','mean')).reset_index() 

    expected['Q6'] = q6.sort_values(['transaction_volume','town_name','centre_name','date_basis'],ascending=[False,True,True,True]).head(20)
    keys = {'Q1':['town_name','flat_type'],'Q2':['town_name','lease_bucket'],
            'Q3':['town_name','sale_year'],'Q4':['town','flat_type'],
            'Q5':['town_name','proximity_class'],'Q6':['town_name','centre_name','date_basis']} 
    
    checks = {} 

    for name, want in expected.items():
        actual = pd.read_csv(ROOT/'results/queries/stage_5'/f'{name}.csv')
        joined = actual.merge(want,on=keys[name],how='outer',suffixes=('_sql','_csv'),indicator=True,validate='1:1')
        assert (joined._merge=='both').all(), name+' mismatching output keys' 

        maximum_error = 0 

        for column in actual.columns.difference(keys[name]):
            left, right = joined[column+'_sql'], joined[column+'_csv'] 

            assert left.isna().equals(right.isna()), (name,column,'NULL mismatch') 

            error = (left-right).abs().max()
            tolerance = 0.051 if column=='avg_distance_m' else 0.011 

            if column.endswith('_count') or column=='transaction_volume': tolerance=0 

            assert pd.isna(error) or error<=tolerance, (name,column,error)
            maximum_error = max(maximum_error, 0 if pd.isna(error) else float(error)) 

        assert (ROOT/'results/queries/stage_5'/f'{name}.csv').read_bytes()==(ROOT/'results/queries/indexed'/f'{name}.csv').read_bytes()
        checks[name] = dict(rows=len(actual),independent_csv_calculation_passed=True,
                           indexed_output_identical=True,max_difference_before_rounding=maximum_error) 
        
    evidence = dict(transaction_rows=len(sales),spatially_classified_rows=len(near),
                    all_six_queries_passed=True,queries=checks) 
    
    (ROOT/'results/independent_validation.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence,indent=2))

if __name__=='__main__':
    main()
