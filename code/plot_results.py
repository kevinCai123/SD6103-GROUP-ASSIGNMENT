"""Recreate report performance figures from the measured CSV files."""
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT=Path(__file__).resolve().parents[1]

def main():
    base=pd.read_csv(ROOT/'results/baseline_measurements.csv')
    indexed=pd.read_csv(ROOT/'results/indexed_measurements.csv')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'axes.labelcolor':'#334155','text.color':'#172b4d'})
    fig,axes=plt.subplots(3,2,figsize=(9.4,9.5),layout='constrained')
    for i,ax in enumerate(axes.flat,1):
        d=base[base['query']==f'Q{i}'].groupby('transaction_rows').execution_ms.agg(['mean','std'])
        ax.errorbar(d.index/1e6,d['mean'],yerr=d['std'],color='#254d75',marker='o',capsize=4,lw=1.8)
        ax.set(title=f'Q{i}',xlabel='Transaction rows (millions)',ylabel='Execution time (ms)',xlim=(.24,1.02),ylim=(0,None))
        ax.grid(axis='y',color='#e2e8f0');ax.set_axisbelow(True)
    fig.suptitle('Baseline runtime as the database grows',fontsize=15,fontweight='bold')
    fig.savefig(ROOT/'report_figures/baseline_scaling.pdf',bbox_inches='tight')
    fig.savefig(ROOT/'report_figures/baseline_scaling.png',dpi=170,bbox_inches='tight')
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(9.4,5.1),layout='constrained')
    final=base[base.stage==5].groupby('query').execution_ms.agg(['mean','std'])
    after=indexed.groupby('query').execution_ms.agg(['mean','std'])
    import numpy as np
    x=np.arange(6)
    ax.bar(x-.19,final['mean'],.38,yerr=final['std'],capsize=4,color='#254d75',label='Baseline')
    ax.bar(x+.19,after['mean'],.38,yerr=after['std'],capsize=4,color='#c68436',label='Four indexes')
    ax.set(xticks=x,xticklabels=final.index,ylabel='Execution time (ms)',ylim=(0,2600))
    ax.set_title('Full database: baseline and indexed runtime',loc='left',fontsize=15,fontweight='bold',pad=16)
    ax.legend(frameon=False,loc='upper left');ax.grid(axis='y',color='#e2e8f0');ax.set_axisbelow(True)
    fig.savefig(ROOT/'report_figures/index_comparison.pdf',bbox_inches='tight')
    fig.savefig(ROOT/'report_figures/index_comparison.png',dpi=170,bbox_inches='tight')
    plt.close(fig)
    print('Created baseline scaling and index comparison figures (mean +/- sample SD, n=5).')

if __name__=='__main__':main()
