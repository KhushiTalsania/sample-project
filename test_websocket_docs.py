"""
Test WebSocket Documentation Endpoints

This script tests that all WebSocket documentation endpoints are visible and working
in the FastAPI documentation.

Usage:
    python test_websocket_docs.py
"""

import asyncio
import aiohttp
import sys
import os
from datetime import datetime
import logging

# Add project root to path
sys.path.append(os.path.dirname(__file__))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WebSocketDocsTester:
    """Test WebSocket documentation endpoints"""
    
    def __init__(self, http_url: str = "http://localhost:8000"):
        self.http_url = http_url
        self.test_results = {
            "timestamp": datetime.now().isoformat(),
            "application": "betting_monolithic_service",
            "overall_status": "UNKNOWN",
            "endpoints": {},
            "summary": {}
        }
        
    async def test_documentation_endpoints(self):
        """Test all WebSocket documentation endpoints"""
        print("📚 Testing WebSocket Documentation Endpoints...")
        endpoints = {}
        
        try:
            async with aiohttp.ClientSession() as session:
                # Test WebSocket overview endpoint
                try:
                    async with session.get(f"{self.http_url}/websocket-overview") as response:
                        if response.status == 200:
                            data = await response.json()
                            endpoints["websocket_overview"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket overview endpoint working"
                            }
                            print("✅ WebSocket overview endpoint working")
                        else:
                            endpoints["websocket_overview"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket overview endpoint failed: {response.status}")
                except Exception as e:
                    endpoints["websocket_overview"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket overview endpoint error: {e}")
                
                # Test WebSocket chat docs endpoint
                try:
                    async with session.get(f"{self.http_url}/ws/chat") as response:
                        if response.status == 200:
                            data = await response.json()
                            endpoints["ws_chat_docs"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket chat docs endpoint working"
                            }
                            print("✅ WebSocket chat docs endpoint working")
                        else:
                            endpoints["ws_chat_docs"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket chat docs endpoint failed: {response.status}")
                except Exception as e:
                    endpoints["ws_chat_docs"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket chat docs endpoint error: {e}")
                
                # Test WebSocket DM docs endpoint
                try:
                    async with session.get(f"{self.http_url}/ws/dm") as response:
                        if response.status == 200:
                            data = await response.json()
                            endpoints["ws_dm_docs"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket DM docs endpoint working"
                            }
                            print("✅ WebSocket DM docs endpoint working")
                        else:
                            endpoints["ws_dm_docs"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket DM docs endpoint failed: {response.status}")
                except Exception as e:
                    endpoints["ws_dm_docs"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket DM docs endpoint error: {e}")
                
                # Test WebSocket threads docs endpoint
                try:
                    async with session.get(f"{self.http_url}/ws/threads") as response:
                        if response.status == 200:
                            data = await response.json()
                            endpoints["ws_threads_docs"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket threads docs endpoint working"
                            }
                            print("✅ WebSocket threads docs endpoint working")
                        else:
                            endpoints["ws_threads_docs"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket threads docs endpoint failed: {response.status}")
                except Exception as e:
                    endpoints["ws_threads_docs"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket threads docs endpoint error: {e}")
                
                # Test WebSocket club chat docs endpoint
                try:
                    async with session.get(f"{self.http_url}/ws/chat/test_club_123") as response:
                        if response.status == 200:
                            data = await response.json()
                            endpoints["ws_club_chat_docs"] = {
                                "status": "PASS",
                                "response": data,
                                "message": "WebSocket club chat docs endpoint working"
                            }
                            print("✅ WebSocket club chat docs endpoint working")
                        else:
                            endpoints["ws_club_chat_docs"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ WebSocket club chat docs endpoint failed: {response.status}")
                except Exception as e:
                    endpoints["ws_club_chat_docs"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ WebSocket club chat docs endpoint error: {e}")
                
                # Test main docs endpoint
                try:
                    async with session.get(f"{self.http_url}/docs") as response:
                        if response.status == 200:
                            endpoints["main_docs"] = {
                                "status": "PASS",
                                "response": {"available": True},
                                "message": "Main API documentation available"
                            }
                            print("✅ Main API documentation available")
                        else:
                            endpoints["main_docs"] = {
                                "status": "FAIL",
                                "response": None,
                                "message": f"HTTP {response.status}"
                            }
                            print(f"❌ Main API documentation failed: {response.status}")
                except Exception as e:
                    endpoints["main_docs"] = {
                        "status": "ERROR",
                        "response": None,
                        "message": str(e)
                    }
                    print(f"❌ Main API documentation error: {e}")
                
        except ImportError:
            print("⚠️ aiohttp not available, skipping documentation tests")
            endpoints["error"] = "aiohttp not available"
        except Exception as e:
            print(f"❌ Documentation endpoints test error: {e}")
            endpoints["error"] = str(e)
        
        return endpoints
    
    async def run_test(self):
        """Run documentation test suite"""
        print("🚀 Starting WebSocket Documentation Test Suite")
        print("=" * 60)
        print(f"Timestamp: {self.test_results['timestamp']}")
        print(f"Application: {self.test_results['application']}")
        print("=" * 60)
        
        # Test documentation endpoints
        print("\n📚 Testing Documentation Endpoints...")
        self.test_results["endpoints"] = await self.test_documentation_endpoints()
        
        # Calculate summary
        self._calculate_summary()
        
        # Print results
        self._print_results()
        
        return self.test_results
    
    def _calculate_summary(self):
        """Calculate test summary"""
        total_endpoints = len(self.test_results["endpoints"])
        working_endpoints = sum(1 for result in self.test_results["endpoints"].values() 
                              if isinstance(result, dict) and result.get("status") == "PASS")
        
        self.test_results["summary"] = {
            "total_endpoints": total_endpoints,
            "working_endpoints": working_endpoints,
            "success_rate": f"{(working_endpoints/total_endpoints)*100:.1f}%" if total_endpoints > 0 else "0%",
            "overall_status": "PASS" if working_endpoints == total_endpoints else "FAIL"
        }
        
        self.test_results["overall_status"] = self.test_results["summary"]["overall_status"]
    
    def _print_results(self):
        """Print test results"""
        print("\n" + "=" * 60)
        print("📊 DOCUMENTATION TEST RESULTS")
        print("=" * 60)
        
        # Overall status
        status_emoji = "🎉" if self.test_results["overall_status"] == "PASS" else "❌"
        print(f"\n{status_emoji} Overall Status: {self.test_results['overall_status']}")
        
        # Endpoints
        print(f"\n📚 Documentation Endpoints:")
        for name, result in self.test_results["endpoints"].items():
            if isinstance(result, dict):
                status = result.get("status", "UNKNOWN")
                emoji = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
                print(f"  {emoji} {name}: {status}")
                if result.get("message"):
                    print(f"      {result['message']}")
        
        # Summary
        summary = self.test_results["summary"]
        print(f"\n📈 Summary:")
        print(f"  Working Endpoints: {summary['working_endpoints']}/{summary['total_endpoints']}")
        print(f"  Success Rate: {summary['success_rate']}")
        
        # Recommendations
        print(f"\n💡 Recommendations:")
        if self.test_results["overall_status"] == "PASS":
            print("  ✅ All WebSocket documentation endpoints are working!")
            print("  📚 Check the API documentation at: http://localhost:8000/docs")
            print("  🔍 Look for 'WebSocket Endpoints' section in the docs")
            print("  🌐 WebSocket paths are now visible in FastAPI documentation")
        else:
            print("  ❌ Some documentation endpoints are not working.")
            print("  🔧 Check the details above for specific problems.")
            print("  🚀 Make sure the main application is running on localhost:8000")
        
        print("\n" + "=" * 60)

async def main():
    """Main test function"""
    print("🚀 WebSocket Documentation Test Runner")
    print("This will test that all WebSocket documentation endpoints are visible in FastAPI docs.")
    print("Make sure the main application is running on localhost:8000")
    print()
    
    tester = WebSocketDocsTester()
    
    try:
        results = await tester.run_test()
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
