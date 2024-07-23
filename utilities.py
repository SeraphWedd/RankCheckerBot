import pickle

def fetch_file(fname):
    data = None
    with open(fname, 'rb') as f:
        data = pickle.load(f)
    return data

def save_file(data, fname='temp.pkl'):
    with open(fname, 'wb') as f:
        pickle.dump(data, f)
