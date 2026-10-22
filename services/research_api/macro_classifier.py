"""One local topic classifier shared by macro and sector views; not a return model."""
import json,hashlib,re
from functools import lru_cache
from .rights import ROOT

@lru_cache(maxsize=1)
def trained_classifier():
    from sklearn.pipeline import Pipeline,FeatureUnion
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score,accuracy_score,log_loss
    raw=(ROOT/'config/macro-topic-training.json').read_bytes();d=json.loads(raw)
    train=d['train'];test=d['validation']
    # No validation rows are fit. Production news is inference-only.
    if set(r['text'].casefold() for r in train)&set(r['text'].casefold() for r in test):raise ValueError('Training/validation overlap')
    model=Pipeline([('features',FeatureUnion([('words',TfidfVectorizer(ngram_range=(1,2),sublinear_tf=True)),('characters',TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=1,sublinear_tf=True))])),('classifier',LogisticRegression(C=3,class_weight='balanced',max_iter=1200,random_state=42))])
    model.fit([r['text'] for r in train],[r['label'] for r in train])
    actual=[r['label'] for r in test];prediction=model.predict([r['text'] for r in test]);probability=model.predict_proba([r['text'] for r in test])
    report={'model_version':d['version'],'training_hash':hashlib.sha256(raw).hexdigest(),'algorithm':'TF-IDF + Logistic Regression','training_rows':len(train),'validation_rows':len(test),
            'macro_f1':round(float(f1_score(actual,prediction,average='macro')),4),'accuracy':round(float(accuracy_score(actual,prediction)),4),
            'log_loss':round(float(log_loss(actual,probability,labels=model.classes_)),4),'majority_baseline_accuracy':max(actual.count(c) for c in set(actual))/len(actual),
            'validation_kind':'held-out authored scenarios; NOT historical financial backtest','return_prediction_validated':False,
            'limitations':['Small curated bilingual training corpus; not expert-labelled production data.','Topic score is not fact verification, causal proof, or probability of market returns.','No market accuracy or P&L claim can be made from these scenario tests.']}
    return model,report

ENTITY_GUARDS={
 'market_access':r'standalone|stand.alone|free.float|reklasifikasi|foreign inclusion|aksesibilitas|investability|konsultasi|downgrade|msci.{0,60}beku|beku.{0,60}msci',
 'energy':r'minyak|brent|wti|energi|energy|bunker|gas alam|natural gas|opec|tanker|drilling|pengeboran|hormuz|crude|oil',
 'global_monetary':r'\bfed\b|federal reserve|treasury|ecb|bunga as|inflasi (?:as|amerika)|dolar global|global liquidity|global central bank',
 'domestic_monetary':r'bank indonesia|bi[- ]rate|rupiah|jisdor|cadangan devisa|bunga domestik|kredit|biaya dana',
 'biodiesel':r'biodiesel|\bb(?:30|35|40|50)\b|\bcpo\b|fame|sawit|palm oil',
 'ai_capex':r'\bai\b|kecerdasan buatan|pusat data|data cent(?:er|re)|hyperscal',
 'domestic_growth':r'pertumbuhan|konsumsi|pdb|gdp|bps|daya beli|apbn|fiskal|perdagangan|pmi|domestic|household',
 'global_equities':r'wall street|s&p|dow jones|dow30|nasdaq|nikkei|hang seng|kospi|shanghai|dax|cac40|ftse|global equit|eido',
 'commodities':r'emas|gold|perak|silver|nikel|nickel|copper|tembaga|coal|batu bara|timah|tin|alumini?um|gandum|wheat|jagung|corn|iron ore|rubber|zinc|commodity|komoditas',
}

def classify_texts(texts):
    model,report=trained_classifier()
    if not texts:return [],report
    probs=model.predict_proba(texts);result=[]
    for text,row in zip(texts,probs):
        idx=int(row.argmax());confidence=float(row[idx]);label=str(model.classes_[idx])
        eligible=confidence>=.28 and (label=='other' or bool(re.search(ENTITY_GUARDS.get(label,r'(?!)'),text,re.I)))
        result.append({'topic':label if eligible else 'unclassified','topic_score':round(confidence,4),'raw_topic':label,'entity_guard_passed':eligible})
    return result,report
