import os, sys, json, datetime
import jwt
import uuid
import hashlib
import util

from urllib.parse import urlencode
import requests

'''
20200327
EXCHANGE API
[주문]
초당 8회, 분당 200회

[주문 외 API]
초당 30회, 분당 900회

[Exchange API 추가 안내 사항]

QUOTATION API
1) Websocket 연결 요청 수 제한
초당 5회, 분당 100회

2) REST API 요청 수 제한
분당 600회, 초당 10회 (종목, 캔들, 체결, 티커, 호가별)
'''
class UpbitWrapper():
    def __init__(self, secret_key, access_key, server_url, market_code):

        self.access_key = access_key 
        self.secret_key = secret_key 
        self.server_url = server_url

        self.market_code =  market_code
        self.account_info = []
        self.rebalance_start_percent = 5 
        self.original_crypto_price = 0

    def setOriginalCryptoPrice(self, price):
        self.original_crypto_price = price

    def setRebalance_percent(self, iPercent):
        self.rebalance_start_percent = iPercent
    
    def checkAssetInfo(self, fiat_balance, current_crypto_price, crypto_balance):

        if( fiat_balance == 0 or current_crypto_price == 0 ):
            return None

        balance_sum = fiat_balance + crypto_balance * current_crypto_price
        fiat_percent = round(fiat_balance/balance_sum * 100, 2)
        crypto_percent = round( (crypto_balance * current_crypto_price )/balance_sum * 100, 2) 

        order_balance = 0
        if( abs(fiat_percent - crypto_percent) > self.rebalance_start_percent ):

            # print( '{} fiat: {}[{} %], crypto price: {} amount: {} [{} %]'.format(
            #     'buy ' if( fiat_percent > crypto_percent ) else 'sell'
            #     ,round(fiat_balance, 2)
            #     ,round(fiat_percent, 2)
            #     ,round(current_crypto_price, 2)
            #     ,round(crypto_balance, 2)
            #     ,round(crypto_percent, 2)
            # ))

            if( fiat_percent > crypto_percent ):
                # 현금 비중이 높은 경우 
                #buy
                order_balance = round((fiat_balance - crypto_balance * current_crypto_price) )  / 2 
                return { "order_type": 'bid', "order_balance": order_balance }
            else:
                # 암호화폐 비중이 높은 경우
                #sell

                # 현재가가 기준가보다 낮은 경우 수익 극대화를 위해 매도  
                if( current_crypto_price < self.original_crypto_price ):
                    order_balance = round((crypto_balance * current_crypto_price - fiat_balance ) ) / 2 
                else:
                    order_balance = 0
                return { "order_type": 'ask', "order_balance": order_balance }

        else:
            return {"order_type": "none", "order_balance": 0} 

    def simulateReblance(self, iFiatBalance, iCryptoBalance, iStartPrice, iEndPrice ):
        fiat_balance = iFiatBalance
        crypto_balance = iCryptoBalance 

        iStartPrice = iStartPrice
        iEndPrice = iEndPrice
        iStep = 0

        if ( iStartPrice > iEndPrice ):
            iStep = -1
        else:
            iStep = 1


        for current_crypto_price in range(iStartPrice, iEndPrice, iStep):
            if( self.isValidPrice(current_crypto_price) == False ):
                continue
            result_list = self.checkAssetInfo(fiat_balance, current_crypto_price, crypto_balance)
            assert "order_type" in result_list


            order_type = result_list['order_type']
            order_balance = result_list['order_balance']

            # buy
            if( order_type == 'bid' ):
                order_balance = order_balance * 0.9995 # 수수료
                crypto_balance += round(order_balance / current_crypto_price, 2)
                fiat_balance -= order_balance
                pass
            elif ( order_type == 'ask' ):
                order_balance = order_balance * 0.9995 # 수수료
                crypto_balance -= round(order_balance / current_crypto_price, 2)
                fiat_balance += order_balance
                pass
            else:
                continue
            pass
        
        return {"fiat_balance": fiat_balance, "crypto_balance": crypto_balance}


    def getAccountInfo(self):
        '''
        [
            {
                "avg_buy_price": "0",
                "avg_buy_price_modified": true,
                "balance": "2.27593723",
                "currency": "KRW",
                "locked": "0.0",
                "unit_currency": "KRW"
            },
            {
                "avg_buy_price": "217.4",
                "avg_buy_price_modified": false,
                "balance": "1.13438041",
                "currency": "XRP",
                "locked": "0.0",
                "unit_currency": "KRW"
            }
        ]
        '''
        payload = {
            'access_key': self.access_key,
            'nonce': str(uuid.uuid4()),
        }

        jwt_token = jwt.encode(payload, self.secret_key).decode('utf-8')
        authorize_token = 'Bearer {}'.format(jwt_token)
        headers = {"Authorization": authorize_token}

        url = self.server_url + "/v1/accounts" 

        try:
            response = requests.get(url, headers=headers)
        except requests.exceptions.SSLError:
            print("ssl error")
            return None 
        except:
            print("except")
            return None 
        else:
            if( response.status_code != 200):
                print("error return")
                return None 
            else:
                output_list = response.json()
                return output_list



    def makeOrder(self, order_type, order_price, order_balance, test = True):
        query = ''
        volume = 0 # for test
        if( order_type == 'none' or order_price == 0 or order_balance == 0):
            return None

        if( order_type == 'bid' ):
            # 암호화폐 매수,매도호가 기준 
            volume = round(order_balance / order_price, 2)
            query = {
                'market': self.market_code,
                'side': 'bid',
                'volume': volume,
                'price': str(order_price),
                'ord_type': 'limit',
            }
        else:
            # 암호화폐 매도,매수호가 기준
            volume = round(order_balance / order_price, 2)
            query = {
                'market': self.market_code,
                'side': 'ask',
                'volume': volume,
                'price': str(order_price),
                'ord_type': 'limit',
            }

        print(query)

        query_string = urlencode(query).encode()

        m = hashlib.sha512()
        m.update(query_string)
        query_hash = m.hexdigest()

        payload = {
            'access_key': self.access_key,
            'nonce': str(uuid.uuid4()),
            'query_hash': query_hash,
            'query_hash_alg': 'SHA512',
        }

        jwt_token = jwt.encode(payload, self.secret_key).decode('utf-8')
        authorize_token = 'Bearer {}'.format(jwt_token)
        headers = {"Authorization": authorize_token}

        url = self.server_url + "/v1/orders"
        try:
            pass
            if( test == True ):
                query = ''
            response = requests.post( url, params=query, headers=headers)
            pass
        except requests.exceptions.SSLError:
            print("ssl error")
            return None 
        except:
            print("except")
            return None 
        else:
            if( response.status_code != 200):
                print("\n\nerror return: \n{}\n{}".format(query, response.text ) )
                return None 
            else:
                output_list = response.json()
                print(json.dumps( response.json(), indent=2, sort_keys=True) )
        pass


    def getOrderbook(self):
        url = self.server_url + "/v1/orderbook"
        query = {"markets": self.market_code }

        try:
            response = requests.get( url, params= query)
        except requests.exceptions.SSLError:
            print("ssl error")
            return None
        except:
            print("except")
            return None 
        else:
            if( response.status_code != 200):
                print("error return: \n{}\n{}".format(query, response.text ) )
                return None 
            else:
                output_list = response.json()
                # print(json.dumps( output_list, indent=2, sort_keys=True) )
                return output_list

    # 최대 200 개까지 가능 
    def getDayCandle(self, last_date_time_to ):
        url = self.server_url + "/v1/candles/days"
        query = {"market": self.market_code, "count": 200, "to": last_date_time_to }

        try:
            response = requests.get( url, params= query)
        except requests.exceptions.SSLError:
            print("ssl error")
            return None
        except:
            print("except")
            return None
        else:
            if( response.status_code != 200):
                print("error return: \n{}\n{}".format(query, response.text ) )
                return None 
            else:
                result = []
                output_list = response.json()
                del_key = ['timestamp', 'candle_acc_trade_price', 'candle_acc_trade_volume', 'prev_closing_price', 'change_price', 'change_rate', 'candle_date_time_utc']

                for item in output_list:
                    list( map(item.pop, del_key) )
                    result.append( item )

                return result

    def isValidPrice(self, price):
            '''
            원화 마켓 주문 가격 단위
            원화 마켓은 호가 별 주문 가격의 단위가 다릅니다. 아래 표를 참고하여 해당 단위로 주문하여 주세요.
            https://docs.upbit.com/v1.0/docs/%EC%9B%90%ED%99%94-%EB%A7%88%EC%BC%93-%EC%A3%BC%EB%AC%B8-%EA%B0%80%EA%B2%A9-%EB%8B%A8%EC%9C%84
            ~10         : 0.01
            ~100        : 0.1
            ~1,000      : 1
            ~10,000     : 5
            ~100,000    : 10
            ~500,000    : 50
            ~1,000,000  : 100
            ~2,000,000  : 500
            +2,000,000  : 1,000
            '''
            if price <= 10:
                if (price*100) != int(price*100):
                    return False
            elif price <= 100:
                if (price*10) != int(price*10):
                    return False
            elif price <= 1000:
                if price != int(price):
                    return False
            elif price <= 10000:
                if (price % 5) != 0:
                    return False
            elif price <= 100000:
                if (price % 10) != 0:
                    return False
            elif price <= 500000:
                if (price % 50) != 0:
                    return False
            elif price <= 1000000:
                if (price % 100) != 0:
                    return False
            elif price <= 2000000:
                if (price % 500) != 0:
                    return False
            elif (price % 1000) != 0:
                return False
            return True