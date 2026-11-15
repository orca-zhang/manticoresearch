"""Transport diagnostic: original upstream vs itself at 32 point clients."""
import run_tls
if __name__ == '__main__':
 matrix=[dict(c,name='transport-aa32-'+str(c['cache_mib'])+'m',aa=True)
        for c in run_tls.cases() if c['name'].startswith('churn-c32-')]
 assert len(matrix)==2 and all(c['clients']==32 and c['batch']==1 for c in matrix)
 run_tls.cases=lambda:matrix
 run_tls.main()
