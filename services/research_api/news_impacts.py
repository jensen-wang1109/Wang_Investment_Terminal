"""Explainable headline-to-industry routing, not company earnings verification."""
import re
RULES=[
 (r'pelayaran|perkapalan|freight|tarif angkut|kapal kontainer|logistik|shipping','IDXTRANS','Transportation & Logistics',['Logistics & Shipment','Transportation Services'], 'Tarif / rute / volume dapat mengubah revenue operator dan biaya pengiriman; net benefit perlu diperiksa.'),
 (r'tanker|angkutan migas','IDXENERGY','Energy',['Oil & Gas Transportation (Tanker)','Oil & Gas Transportation (Offshore)'],'Eksposur kapal khusus migas; kontrak, charter dan bunker menentukan dampak.'),
 (r'harga minyak|pasokan minyak|migas|gas alam|lng|krisis energi','IDXENERGY','Energy',['Oil & Gas','Coal'],'Harga energi memengaruhi ASP produsen dan biaya pengguna secara berlawanan.'),
 (r'harga batu ?bara|batubara|thermal coal|coking coal','IDXENERGY','Energy',['Coal','Coal Transportation'],'Bedakan thermal dan metallurgical coal; harga, DMO dan volume tidak selalu searah.'),
 (r'emas|gold','IDXBASIC','Basic Materials',['Gold'],'Harga jual emas dapat mendukung miner, tetapi biaya dan volume tetap menentukan.'),
 (r'nikel|nickel','IDXBASIC','Basic Materials',['Nickel'],'Demand naik dapat disertai oversupply; jangan menyamakan produksi dan profitabilitas.'),
 (r'tembaga|copper|timah|alumini?um|baja','IDXBASIC','Basic Materials',['Copper / metals','Tin','Steel'],'Perubahan supply-demand logam, biaya dan substitusi perlu dipisahkan.'),
 (r'cpo|sawit|biodiesel|\bb[345]0\b|pangan|gandum','IDXNONCYC','Consumer Non-Cyclicals',['Palm Oil','Agricultural Products','Food Producers'],'Produsen dan pengguna bahan baku dapat terkena dampak berbeda; komoditas harus cocok.'),
 (r'bi[- ]rate|suku bunga|bank|kredit|perbankan','IDXFINANCE','Financials',['Banking','Financing'],'Pendanaan, repricing kredit, kualitas aset dan demand perlu dibaca bersama.'),
 (r'properti|property|kpr|perumahan|real estate','IDXPROPERT','Properties & Real Estate',['Property'],'Affordability, presales dan biaya pendanaan menjadi jalur transmisi.'),
 (r'pusat data|data cent(?:er|re)|infrastruktur ai|cloud|kecerdasan buatan','IDXTECHNO','Technology',['Data Center, AI & Cloud Infrastructure','IT Service & Integrator, ICT'],'Capex teknologi menjadi hipotesis demand; kontrak dan utilisasi perlu konfirmasi.'),
 (r'pusat data|infrastruktur ai|kabel|transformator|elektrifikasi','IDXINDUST','Industrials',['Electrical','Industrial Goods'],'Power capex dapat memengaruhi backlog supplier; bahan baku juga dapat menambah biaya.'),
 (r'tol|infrastruktur|telekomunikasi|listrik|geothermal','IDXINFRA','Infrastructures',['Infrastructure','Telecommunication','Renewable Energy'],'Capex, tarif, regulasi dan utilisasi menentukan dampak industri.'),
 (r'rumah sakit|farmasi|kesehatan','IDXHEALTH','Healthcare',['Hospital','Pharmaceuticals'],'Kaitan demand layanan / produk; bukan kesimpulan margin seluruh sektor.'),
 (r'otomotif|mobil|kendaraan|pariwisata|wisata|ritel|retail','IDXCYCLIC','Consumer Cyclicals',['Automobiles','Tourism & Recreation','Retail'],'Permintaan diskresioner sensitif daya beli, kredit dan harga input.')]

def impacts(title):
    return [{'sector':sector,'sector_name':name,'industries':industries,'reason':reason,
             'status':'headline_linkage','direction':'conditional','method':'news-sector-tags-v1'}
        for pattern,sector,name,industries,reason in RULES if re.search(pattern,title,re.I)]
