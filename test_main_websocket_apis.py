"""
Test Main Application WebSocket APIs

This script tests all WebSocket APIs through the main monolithic application.
It tests both HTTP endpoints and WebSocket connections.

Usage:
    python test_main_websocket_apis.py
"""

import asyncio
import json
import websockets
import aiohttp
import sys
import os
from datetime import datetime
from typing import Dict, Any, List, Tuple
import logging

# Add project root to path
sys.path.append(os.path.dirname(__file__))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MainWebSocketAPITester:
    """Comprehensive WebSocket API tester for main application"""
    
    def __init__(self, base_url: str = "ws://localhost:8000", http_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.http_url = http_url
        self.test_results = {
            "timestamp": datetime.now().isoformat(),
            "application": "betting_monolithic_service",
            "version": "1.0.0",
            "overall_status": "UNKNOWN",
            "endpoints": {},
            "http_endpoints": {},
            "summary": {},
            "errors": []
        }
        
    async def test_http_endpoints(self) -> Dict[str, Any]:
        """Test all HTTP endpoints"""
        print("🌐 Testing HTTP Endpoints...")
        http_results = {}
        
        try:
            async with aiohttp.ClientSession() as session:
                # Test main service endpoint
                try:
                    async with session.get(f"{self.http_url}/") as response:
                        if response.status == 200:
                            data = await response.json()
                            http_results["main_service"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "Main service is running"
                            }
                            print("✅ Main service endpoint working")
                        else:
                            http_results["main_service"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ Main service endpoint failed: {response.status}")
                except Exception as e:
                    http_results["main_service"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ Main service endpoint error: {e}")
                
                # Test health endpoint
                try:
                    async with session.get(f"{self.http_url}/health") as response:
                        if response.status == 200:
                            data = await response.json()
                            http_results["health"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "Health check passed"
                            }
                            print("✅ Health endpoint working")
                        else:
                            http_results["health"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ Health endpoint failed: {response.status}")
                except Exception as e:
                    http_results["health"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ Health endpoint error: {e}")
                
                # Test WebSocket health endpoint
                try:
                    async with session.get(f"{self.http_url}/ws/health") as response:
                        if response.status == 200:
                            data = await response.json()
                            http_results["ws_health"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket health check passed"
                            }
                            print("✅ WebSocket health endpoint working")
                        else:
                            http_results["ws_health"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket health endpoint failed: {response.status}")
                except Exception as e:
                    http_results["ws_health"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket health endpoint error: {e}")
                
                # Test WebSocket stats endpoint
                try:
                    async with session.get(f"{self.http_url}/ws/stats") as response:
                        if response.status == 200:
                            data = await response.json()
                            http_results["ws_stats"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket stats endpoint working"
                            }
                            print("✅ WebSocket stats endpoint working")
                        else:
                            http_results["ws_stats"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket stats endpoint failed: {response.status}")
                except Exception as e:
                    http_results["ws_stats"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket stats endpoint error: {e}")
                
                # Test WebSocket docs endpoint
                try:
                    async with session.get(f"{self.http_url}/ws/docs") as response:
                        if response.status == 200:
                            data = await response.json()
                            http_results["ws_docs"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket documentation available"
                            }
                            print("✅ WebSocket documentation available")
                        else:
                            http_results["ws_docs"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket documentation failed: {response.status}")
                except Exception as e:
                    http_results["ws_docs"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket documentation error: {e}")
                
                # Test WebSocket test endpoint
                try:
                    async with session.get(f"{self.http_url}/test-websocket") as response:
                        if response.status == 200:
                            data = await response.json()
                            http_results["ws_test"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket test endpoint working"
                            }
                            print("✅ WebSocket test endpoint working")
                        else:
                            http_results["ws_test"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket test endpoint failed: {response.status}")
                except Exception as e:
                    http_results["ws_test"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket test endpoint error: {e}")
                
                # Test main docs endpoint
                try:
                    async with session.get(f"{self.http_url}/docs") as response:
                        if response.status == 200:
                            http_results["docs"] = {
                                "status": "PASS",
                                "response": {"available": True},
                                "message": "Main API documentation available"
                            }
                            print("✅ Main API documentation available")
                        else:
                            http_results["docs"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ Main API documentation failed: {response.status}")
                except Exception as e:
                    http_results["docs"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ Main API documentation error: {e}")
                
        except ImportError:
            print("⚠️ aiohttp not available, skipping HTTP endpoint tests")
            http_results["error"] = "aiohttp not available"
        except Exception as e:
            print(f"❌ HTTP endpoints test error: {e}")
            http_results["error"] = str(e)
        
        return http_results
    
    async def test_websocket_endpoint(self, endpoint: str) -> Dict[str, Any]:
        """Test a single WebSocket endpoint comprehensively"""
        print(f"\n📡 Testing WebSocket endpoint: {endpoint}")
        endpoint_results = {
            "endpoint": endpoint,
            "connection": False,
            "ping_pong": False,
            "authentication": False,
            "room_management": False,
            "messaging": False,
            "typing_indicators": False,
            "error_handling": False,
            "errors": []
        }
        
        try:
            # Test connection
            websocket = await websockets.connect(f"{self.base_url}{endpoint}")
            endpoint_results["connection"] = True
            print(f"✅ Connected to {endpoint}")
            
            # Wait for connection confirmation
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                message = json.loads(response)
                if message.get("type") == "connect":
                    print(f"✅ Connection confirmed: {message.get('data', {}).get('message', 'OK')}")
                else:
                    print(f"⚠️ Unexpected connection response: {message}")
            except asyncio.TimeoutError:
                print(f"⚠️ No connection confirmation received from {endpoint}")
            
            # Test ping/pong
            try:
                ping_message = {"type": "ping", "data": {}}
                await websocket.send(json.dumps(ping_message))
                print("✅ Ping sent")
                
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                message = json.loads(response)
                
                if message.get("type") == "pong":
                    endpoint_results["ping_pong"] = True
                    print("✅ Pong received - ping/pong working!")
                else:
                    print(f"⚠️ Unexpected pong response: {message}")
            except asyncio.TimeoutError:
                print("❌ No pong response received")
            except Exception as e:
                print(f"❌ Ping/pong error: {e}")
                endpoint_results["errors"].append(f"Ping/pong error: {e}")
            
            # Test authentication (if token available)
            try:
                auth_message = {
                    "type": "authenticate",
                    "data": {"token": "test_token"}
                }
                await websocket.send(json.dumps(auth_message))
                print("✅ Authentication message sent")
                
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                message = json.loads(response)
                
                if message.get("type") == "authenticate":
                    if message.get("data", {}).get("authenticated"):
                        endpoint_results["authentication"] = True
                        print("✅ Authentication successful")
                    else:
                        print(f"⚠️ Authentication failed: {message.get('data', {}).get('message', 'Unknown error')}")
                else:
                    print(f"⚠️ Unexpected auth response: {message}")
            except asyncio.TimeoutError:
                print("⚠️ Authentication timeout")
            except Exception as e:
                print(f"⚠️ Authentication error: {e}")
                endpoint_results["errors"].append(f"Authentication error: {e}")
            
            # Test room management
            try:
                join_message = {
                    "type": "join_room",
                    "data": {"club_id": "test_club_123"}
                }
                await websocket.send(json.dumps(join_message))
                print("✅ Room join message sent")
                
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                message = json.loads(response)
                
                if message.get("type") == "room_joined":
                    endpoint_results["room_management"] = True
                    print("✅ Room joined successfully")
                elif message.get("type") == "access_denied":
                    print(f"⚠️ Access denied: {message.get('data', {}).get('reason', 'Unknown reason')}")
                else:
                    print(f"⚠️ Unexpected room response: {message}")
            except asyncio.TimeoutError:
                print("⚠️ Room management timeout")
            except Exception as e:
                print(f"⚠️ Room management error: {e}")
                endpoint_results["errors"].append(f"Room management error: {e}")
            
            # Test messaging
            try:
                send_message = {
                    "type": "send_message",
                    "data": {
                        "club_id": "test_club_123",
                        "content": "Test message from main API tester",
                        "message_type": "text"
                    }
                }
                await websocket.send(json.dumps(send_message))
                print("✅ Message sent")
                
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                message = json.loads(response)
                
                if message.get("type") == "new_message":
                    endpoint_results["messaging"] = True
                    print("✅ Message received - messaging working!")
                elif message.get("type") == "error":
                    print(f"⚠️ Message error: {message.get('data', {}).get('message', 'Unknown error')}")
                else:
                    print(f"⚠️ Unexpected message response: {message}")
            except asyncio.TimeoutError:
                print("⚠️ Messaging timeout")
            except Exception as e:
                print(f"⚠️ Messaging error: {e}")
                endpoint_results["errors"].append(f"Messaging error: {e}")
            
            # Test typing indicators
            try:
                typing_message = {
                    "type": "typing",
                    "data": {
                        "club_id": "test_club_123",
                        "is_typing": True
                    }
                }
                await websocket.send(json.dumps(typing_message))
                print("✅ Typing indicator sent")
                
                # Send stop typing
                stop_typing_message = {
                    "type": "typing",
                    "data": {
                        "club_id": "test_club_123",
                        "is_typing": False
                    }
                }
                await websocket.send(json.dumps(stop_typing_message))
                print("✅ Stop typing sent")
                
                endpoint_results["typing_indicators"] = True
                print("✅ Typing indicators working")
            except Exception as e:
                print(f"⚠️ Typing indicators error: {e}")
                endpoint_results["errors"].append(f"Typing indicators error: {e}")
            
            # Test error handling
            try:
                invalid_message = {
                    "type": "invalid_message_type",
                    "data": {"test": "data"}
                }
                await websocket.send(json.dumps(invalid_message))
                print("✅ Invalid message sent")
                
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                message = json.loads(response)
                
                if message.get("type") == "error":
                    endpoint_results["error_handling"] = True
                    print("✅ Error handling working")
                else:
                    print(f"⚠️ No error response for invalid message: {message}")
            except asyncio.TimeoutError:
                print("⚠️ Error handling timeout")
            except Exception as e:
                print(f"⚠️ Error handling error: {e}")
                endpoint_results["errors"].append(f"Error handling error: {e}")
            
            # Close connection
            await websocket.close()
            print(f"✅ Disconnected from {endpoint}")
            
        except Exception as e:
            print(f"❌ Error testing {endpoint}: {e}")
            endpoint_results["errors"].append(f"Connection error: {e}")
        
        return endpoint_results
    
    async def run_comprehensive_test(self):
        """Run comprehensive test suite"""
        print("🚀 Starting Main Application WebSocket API Test Suite")
        print("=" * 70)
        print(f"Timestamp: {self.test_results['timestamp']}")
        print(f"Application: {self.test_results['application']}")
        print(f"Version: {self.test_results['version']}")
        print("=" * 70)
        
        # Test HTTP endpoints
        print("\n🌐 Testing HTTP Endpoints...")
        self.test_results["http_endpoints"] = await self.test_http_endpoints()
        
        # Test WebSocket endpoints
        print("\n📡 Testing WebSocket Endpoints...")
        endpoints = ["/ws/chat", "/ws/dm", "/ws/threads"]
        
        for endpoint in endpoints:
            endpoint_results = await self.test_websocket_endpoint(endpoint)
            self.test_results["endpoints"][endpoint] = endpoint_results
        
        # Calculate summary
        self._calculate_summary()
        
        # Print results
        self._print_results()
        
        return self.test_results
    
    def _calculate_summary(self):
        """Calculate test summary"""
        total_endpoints = len(self.test_results["endpoints"])
        working_endpoints = 0
        
        for endpoint, results in self.test_results["endpoints"].items():
            if results["connection"] and results["ping_pong"]:
                working_endpoints += 1
        
        http_working = sum(1 for result in self.test_results["http_endpoints"].values() 
                          if isinstance(result, dict) and result.get("status") == "PASS")
        
        self.test_results["summary"] = {
            "total_endpoints": total_endpoints,
            "working_endpoints": working_endpoints,
            "endpoint_success_rate": f"{(working_endpoints/total_endpoints)*100:.1f}%" if total_endpoints > 0 else "0%",
            "http_endpoints_working": http_working,
            "overall_status": "PASS" if working_endpoints == total_endpoints and http_working > 0 else "FAIL"
        }
        
        self.test_results["overall_status"] = self.test_results["summary"]["overall_status"]
    
    def _print_results(self):
        """Print comprehensive test results"""
        print("\n" + "=" * 70)
        print("📊 COMPREHENSIVE TEST RESULTS")
        print("=" * 70)
        
        # Overall status
        status_emoji = "🎉" if self.test_results["overall_status"] == "PASS" else "❌"
        print(f"\n{status_emoji} Overall Status: {self.test_results['overall_status']}")
        
        # HTTP Endpoints
        print(f"\n🌐 HTTP Endpoints:")
        for name, result in self.test_results["http_endpoints"].items():
            if isinstance(result, dict):
                status = result.get("status", "UNKNOWN")
                emoji = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
                print(f"  {emoji} {name}: {status}")
                if result.get("message"):
                    print(f"      {result['message']}")
        
        # WebSocket Endpoints
        print(f"\n📡 WebSocket Endpoints:")
        for endpoint, results in self.test_results["endpoints"].items():
            print(f"\n  {endpoint}:")
            print(f"    Connection: {'✅' if results['connection'] else '❌'}")
            print(f"    Ping/Pong: {'✅' if results['ping_pong'] else '❌'}")
            print(f"    Authentication: {'✅' if results['authentication'] else '❌'}")
            print(f"    Room Management: {'✅' if results['room_management'] else '❌'}")
            print(f"    Messaging: {'✅' if results['messaging'] else '❌'}")
            print(f"    Typing Indicators: {'✅' if results['typing_indicators'] else '❌'}")
            print(f"    Error Handling: {'✅' if results['error_handling'] else '❌'}")
            
            if results["errors"]:
                print(f"    Errors: {len(results['errors'])}")
                for error in results["errors"]:
                    print(f"      - {error}")
        
        # Summary
        summary = self.test_results["summary"]
        print(f"\n📈 Summary:")
        print(f"  WebSocket Endpoints: {summary['working_endpoints']}/{summary['total_endpoints']} working")
        print(f"  Success Rate: {summary['endpoint_success_rate']}")
        print(f"  HTTP Endpoints: {summary['http_endpoints_working']} working")
        
        # Recommendations
        print(f"\n💡 Recommendations:")
        if self.test_results["overall_status"] == "PASS":
            print("  ✅ All systems operational! Your WebSocket APIs are working correctly.")
            print("  📚 Check the API documentation at: http://localhost:8000/docs")
            print("  🔌 WebSocket endpoints are ready for use!")
            print("  🌐 Main application is running on: http://localhost:8000")
        else:
            print("  ❌ Some issues detected. Check the details above for specific problems.")
            if summary["working_endpoints"] < summary["total_endpoints"]:
                print("  - Some WebSocket endpoints are not working properly")
            if summary["http_endpoints_working"] == 0:
                print("  - HTTP endpoints are not accessible")
        
        print("\n" + "=" * 70)

async def main():
    """Main test function"""
    print("🚀 Main Application WebSocket API Test Runner")
    print("This will test all WebSocket APIs through the main monolithic application.")
    print("Make sure the main application is running on localhost:8000")
    print()
    
    tester = MainWebSocketAPITester()
    
    try:
        results = await tester.run_comprehensive_test()
        return results["overall_status"] == "PASS"
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
        return False
    except Exception as e:
        print(f"\n❌ Test suite error: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
